"""Card-level fraud analytics: episode reconstruction, signals, pattern, calibrated probability and
prosecution/defence evidence for one alert. Pure functions over plain dicts (stdlib only); the agent
feeds it TigerGraph query results. Parameters are fitted by scripts/eval_analytics.py on the bank's
closed cases (Jul-Aug) and stored in data_prep/calibration.json.

Txn record keys: id, ts ("YYYY-MM-DD HH:MM:SS"), amount, product, channel, risk, addr1, addr2, dist1,
p_email, r_email, m_flags, c1, c13, d1, d15, model_score, device, dev_status, proxy.
"""
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

CAL_PATH = Path(__file__).resolve().parents[2] / "data_prep" / "calibration.json"
# Used only until calibration.json exists (scripts/eval_analytics.py writes it).
DEFAULT_CAL = {
    "episode_score": 0.5,     # model_score at which a txn counts as fraud-like (evidence text, new phone)
    "member_coef": [], "member_intercept": 0.0,
    "member_tau": 0.8,        # without fitted member_coef, membership falls back to model_score >= 0.8
    "episode_gap_h": 48,      # closed cases split a card's fraud into episodes at gaps >= 48 h
    "episode_days": 10,
    "coef": {}, "intercept": 0.0, "prior_shift": 0.0,
    "fraud_at": 0.85, "legit_at": 0.15,
}
MODEL_REF = "model:closed_case_classifier"
SMALL_AUTH = 10.0           # "tiny" authorization for card testing (README: often under $5)


def load_calibration(path=CAL_PATH):
    try:
        return {**DEFAULT_CAL, **json.loads(Path(path).read_text())}
    except FileNotFoundError:
        return dict(DEFAULT_CAL)


_CAL = None


def _cal():
    global _CAL
    if _CAL is None:
        _CAL = load_calibration()
    return _CAL


def _t(s):
    return datetime.fromisoformat(s)


def _h(a, b):
    return (b - a).total_seconds() / 3600


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _usd(x):
    return f"${x:,.2f}"


# ---------------------------------------------------------------- episode

MEMBER_FEATS = ["logit_model", "risk", "same_channel", "same_device", "same_email", "same_region", "same_product",
                 "same_account_age", "log_amount_diff", "log_hours_apart", "dev_new", "proxy", "online"]


def member_features(r, f):
    """Features of card txn r relative to the flagged txn f, for 'is r in the same fraud episode'.
    same_account_age: txn date minus D1 (a Vesta time delta, apparently days since the card/account
    was first seen) agrees within a day, i.e. likely the same underlying account."""
    age = r["d1"] >= 0 and f["d1"] >= 0 and abs((r["_t"].toordinal() - r["d1"]) - (f["_t"].toordinal() - f["d1"])) <= 1
    return [_logit(r["model_score"]), r["risk"], r["channel"] == f["channel"],
            bool(r["device"]) and r["device"] == f["device"], r["p_email"] == f["p_email"], r["addr1"] == f["addr1"],
            r["product"] == f["product"], age, abs(math.log((abs(r["amount"]) + 1) / (abs(f["amount"]) + 1))),
            math.log1p(abs(_h(f["_t"], r["_t"]))), r["dev_status"] == "New", bool(r["proxy"]), r["channel"] == "online"]


def member_prob(r, f, cal):
    if not cal.get("member_coef"):
        return r["model_score"]
    z = cal["member_intercept"] + sum(w * float(x) for w, x in zip(cal["member_coef"], member_features(r, f)))
    return 1 / (1 + math.exp(-z))


def find_episode(txns, fi, cal):
    """Indices of the fraud episode around txns[fi]: card txns within episode_days of the flag whose
    membership probability (member_features, fitted on closed cases) is >= member_tau, chained in time
    with gaps < episode_gap_h (closed cases split a card's fraud into episodes at 48 h gaps).
    The flag is always included."""
    f, gap, days = txns[fi], cal["episode_gap_h"], cal["episode_days"]
    idx = [i for i, r in enumerate(txns) if i == fi or (abs(_h(f["_t"], r["_t"])) <= 24 * days
                                                         and member_prob(r, f, cal) >= cal["member_tau"])]
    k = idx.index(fi)
    lo = hi = k
    while lo > 0 and _h(txns[idx[lo - 1]]["_t"], txns[idx[lo]]["_t"]) < gap:
        lo -= 1
    while hi < len(idx) - 1 and _h(txns[idx[hi]]["_t"], txns[idx[hi + 1]]["_t"]) < gap:
        hi += 1
    return idx[lo:hi + 1]


def _testing_runs(txns):
    """Card-testing runs: >=3 small online auths within 1 h. Returns list of index lists."""
    small = [i for i, r in enumerate(txns) if r["channel"] == "online" and abs(r["amount"]) < SMALL_AUTH]
    runs, j = [], 0
    for i in range(len(small)):
        while _h(txns[small[j]]["_t"], txns[small[i]]["_t"]) > 1:
            j += 1
        if i - j + 1 >= 3:
            if runs and runs[-1][-1] >= small[j]:
                runs[-1] = sorted(set(runs[-1]) | set(small[j:i + 1]))
            else:
                runs.append(small[j:i + 1])
    return runs


def _structuring(txns, fi):
    """>=3 online purchases within 1 h of each other, each just under $500 ($450-$499.99), near the flag."""
    f = txns[fi]["_t"]
    near = [i for i, r in enumerate(txns) if r["channel"] == "online" and 450 <= abs(r["amount"]) < 500
            and abs(_h(r["_t"], f)) <= 24]
    best = []
    for a in near:
        grp = [b for b in near if 0 <= _h(txns[a]["_t"], txns[b]["_t"]) <= 1]
        if len(grp) > len(best):
            best = grp
    return best if len(best) >= 3 else []


def _recurring(txns, fi):
    """Earlier txns with the same product and amount within 2%, spaced roughly monthly (25-35 days)."""
    f = txns[fi]
    same = [r for r in txns[:fi] if r["product"] == f["product"] and f["amount"]
            and abs(r["amount"] - f["amount"]) <= 0.02 * abs(f["amount"])]
    hits = [r for r in same if any(25 <= (_h(r["_t"], s["_t"]) / 24) % 30.4 <= 35 or
                                   (_h(r["_t"], s["_t"]) / 24) % 30.4 <= 5 and _h(r["_t"], s["_t"]) > 24 * 20
                                   for s in same + [f] if s is not r and s["_t"] > r["_t"])]
    return [r["id"] for r in hits]


def _ring(device_ctx, own_ids):
    """Device ring: a rare device profile used as New, behind an anonymous proxy, by >= 3 other cards in
    the window (the closed cases' undocumented ring: one Samsung profile, 20+ cards, all New + anonymous).
    Common profiles (many cards, mostly not New) are not rings. Returns (card ids, detail) or ([], None)."""
    if not device_ctx or not device_ctx.get("cards"):
        return [], None
    others = [c for c in device_ctx["cards"] if not own_ids & set(c.get("txns") or [])]
    new_others = [c for c in others if c.get("n_new", 0) > 0]
    anon = [c for c in new_others if any("ANONYMOUS" in (p or "") for p in c.get("proxy") or [])]
    ever_cards = device_ctx.get("ever_cards") or len(device_ctx["cards"])
    if len(anon) >= 3 and len(anon) >= 0.6 * len(new_others) and ever_cards <= 100:
        cases = sorted({k for c in anon for k in c.get("cases") or []})
        return sorted(c["id"] for c in anon), {"ever_cards": ever_cards, "anon_cards": len(anon), "cases": cases}
    return [], None


SHARED_MAX_CARDS = 20       # "rare" device profile: used by at most this many cards ever


def _shared_origin(device_ctx, flag, opened, exclude):
    """R6 shared origin on a rare device: the flagged online txn's device profile (<= 20 cards ever) and its
    purchaser->recipient email pair also appear on >= 2 other cards from 7 days before the flag up to opening.
    Audit of Aug-Oct online txns on rare devices: 48% in confirmed fraud cases with such a match (n=1,328)
    vs 11% without (n=11,545). Other cards' txns come from device_ctx["recent_txns"] (with card_id).
    Returns (card ids, matching txns) or ([], [])."""
    if (not device_ctx or flag["channel"] != "online" or flag["device"] != device_ctx["device_id"]
            or not (flag["p_email"] and flag["r_email"]) or not 0 < device_ctx.get("ever_cards", 0) <= SHARED_MAX_CARDS):
        return [], []
    lo = flag["_t"] - timedelta(days=7)
    hits = sorted((r for r in device_ctx.get("recent_txns") or [] if r["card_id"] not in exclude
                   and r["device"] == flag["device"] and (r["p_email"], r["r_email"]) == (flag["p_email"], flag["r_email"])
                   and lo <= _t(r["ts"]) <= opened), key=lambda r: r["ts"])
    cards = sorted({r["card_id"] for r in hits})
    return (cards, hits) if len(cards) >= 2 else ([], [])


CLEAN_ACCOUNT_N, CLEAN_ACCOUNT_DAYS = 5, 7   # account history: >= 5 account txns at least 7 days before the flag


def _account(txns, fi):
    """Earlier card txns on the flagged txn's underlying account: a card mixes several accounts; an account is
    the billing region addr1 plus txn date minus D1 (days since the account was first seen) within a day,
    only when D1 > 0."""
    f = txns[fi]
    if not f["addr1"] or not (f["d1"] or 0) > 0:
        return []
    key = f["_t"].toordinal() - f["d1"]
    return [r for r in txns[:fi] if r["addr1"] == f["addr1"] and (r["d1"] or 0) > 0
            and abs(r["_t"].toordinal() - r["d1"] - key) <= 1]


# ---------------------------------------------------------------- main

def assess(card_txns, flag_id, opened_at, trigger_type, device_ctx=None, customer_ctx=None, cal=None):
    cal = cal or _cal()
    customer_ctx = customer_ctx or {}
    opened = _t(opened_at)
    txns = sorted((dict(r, _t=_t(r["ts"])) for r in card_txns if _t(r["ts"]) <= opened), key=lambda r: r["_t"])
    fi = next(i for i, r in enumerate(txns) if r["id"] == flag_id)
    flag = txns[fi]
    card_ref = customer_ctx.get("card_id", "card")
    hist_ref = f"query:card_history(card_id={card_ref}, window=60d)"

    ep = find_episode(txns, fi, cal)
    ring_cards, ring = _ring(device_ctx, {r["id"] for r in txns})
    if ring_cards:  # the bank's ring cases hold exactly the card's txns on the ring device (4 of 4)
        ep = sorted({fi} | {i for i, r in enumerate(txns) if r["device"] == device_ctx["device_id"]})
    struct = _structuring(txns, fi)
    if struct and fi in struct:
        ep = sorted(set(ep) | set(struct))
    # R5 sequence: a run of small online auths ending within 24 h before the flag (or containing it),
    # followed by a larger online purchase up to the flag
    run = next((r for r in _testing_runs(txns) if r[0] <= fi and _h(txns[r[-1]]["_t"], flag["_t"]) <= 24), None)
    later_big = [i for i in range(run[-1] + 1, fi + 1) if txns[i]["channel"] == "online"
                 and abs(txns[i]["amount"]) >= 2 * SMALL_AUTH] if run else []
    sequence = bool(later_big)
    if sequence:
        ep = sorted(set(ep) | set(run) | set(later_big))
    ep_rows = [txns[i] for i in ep]
    ep_ids = {r["id"] for r in ep_rows}
    amts_ep = [abs(r["amount"]) for r in ep_rows]
    # closed-case labelling of card testing: an online-only episode of >= 5 txns with a tiny (< $5)
    # authorization and a much larger purchase (13 of 13 card-testing cases, 4 of ~2,000 other episodes)
    card_testing = sequence or (len(ep_rows) >= 5 and all(r["channel"] == "online" for r in ep_rows)
                                and min(amts_ep) < 5 and max(amts_ep) >= 20)
    t0 = ep_rows[0]["_t"]
    prior = [r for r in txns if r["_t"] < t0 and r["id"] not in ep_ids]

    # home region: customer-wide counts if the agent supplied them, else this card's history
    counts = Counter(customer_ctx.get("region_counts") or {})
    if counts:
        counts.subtract(r["addr1"] for r in ep_rows if r["addr1"])
    else:
        counts = Counter(r["addr1"] for r in txns if r["addr1"] and r["id"] not in ep_ids)
    counts = +counts
    home = counts.most_common(1)[0][0] if counts else ""
    prior_regions = {r["addr1"] for r in prior if r["addr1"]}
    prior_devices = {r["device"] for r in prior if r["device"]}
    prior_products = Counter(r["product"] for r in prior)
    amts = sorted(abs(r["amount"]) for r in prior)
    med = amts[len(amts) // 2] if amts else 0.0

    channels = {r["channel"] for r in ep_rows}
    ep_regions = [r["addr1"] for r in ep_rows if r["addr1"]]
    away = [a for a in ep_regions if home and a != home]

    # trip: in-person use on several days in one non-home region while home activity continues
    trip_region = flag["addr1"] if flag["channel"] == "in_person" and flag["addr1"] and flag["addr1"] != home else ""
    trip_days, home_during = set(), 0
    if trip_region:
        there = [r for r in txns if r["addr1"] == trip_region and r["channel"] == "in_person"]
        trip_days = {r["_t"].date() for r in there}
        a, b = there[0]["_t"], there[-1]["_t"]
        home_during = sum(1 for r in txns if a - timedelta(days=1) <= r["_t"] <= b + timedelta(days=1)
                          and r["addr1"] == home)
    trip_signature = len(trip_days) >= 2 and home_during > 0
    # new phone: flag from a device marked New, and that device keeps being used on the card afterwards
    # with low model scores, i.e. it became the cardholder's normal device
    same_dev = [r for r in txns if flag["device"] and r["device"] == flag["device"] and r["id"] != flag["id"]]
    new_phone_signature = (not ring_cards and flag["channel"] == "online" and flag["dev_status"] == "New" and len(same_dev) >= 1
                           and max(r["model_score"] for r in same_dev) < cal["episode_score"])
    recurring = _recurring(txns, fi)
    cases = customer_ctx.get("cases") or []
    prior_fraud_cases = [c["id"] for c in cases if c.get("outcome") == "confirmed_fraud"]
    # account history: earlier txns on the flag's account and the closed cases (opened before opening) they are in.
    # Only when the agent read the card's closed cases (customer_ctx["case_txns"]: txn id -> (case, outcome, opened_at))
    acct = _account(txns, fi) if "case_txns" in customer_ctx else []
    case_txns = customer_ctx.get("case_txns") or {}
    acct_cases = {r["id"]: case_txns[r["id"]] for r in acct if r["id"] in case_txns and _t(case_txns[r["id"]][2]) < opened}
    acct_fraud = {t: c for t, (c, o, _) in acct_cases.items() if o == "confirmed_fraud"}
    acct_old = [r for r in acct if _h(r["_t"], flag["_t"]) >= 24 * CLEAN_ACCOUNT_DAYS]
    clean_account = (not acct_cases and len(acct_old) >= CLEAN_ACCOUNT_N
                     and not customer_ctx.get("case_txns_partial"))

    sig = {
        "flag_score": round(flag["model_score"], 4),
        "episode_n": len(ep_rows),
        "episode_max_score": round(max(r["model_score"] for r in ep_rows), 4),
        "episode_mean_score": round(sum(r["model_score"] for r in ep_rows) / len(ep_rows), 4),
        "card_testing": card_testing,
        "card_testing_sequence_1h": sequence,
        "cleared_purchase_over_100": card_testing and any(
            abs(r["amount"]) > 100 for r in ep_rows if r["_t"] > (txns[run[0]]["_t"] if run else t0)),
        "near_threshold_structuring": bool(struct),
        "new_device": any(r["dev_status"] == "New" for r in ep_rows),
        "device_unseen": bool(flag["device"]) and flag["device"] not in prior_devices,
        "anonymous_proxy": any("ANONYMOUS" in r["proxy"] for r in ep_rows),
        "burst_48h": sum(1 for r in ep_rows if abs(_h(r["_t"], flag["_t"])) <= 48),
        "product_new": bool(prior) and flag["product"] not in prior_products,
        "amount_ratio": round(abs(flag["amount"]) / med, 2) if med else None,
        "home_region": home,
        "region_new": bool(flag["addr1"]) and bool(prior) and flag["addr1"] not in prior_regions,
        "away_from_home": bool(away),
        "trip_signature": trip_signature,
        "trip_days": len(trip_days),
        "home_activity_continues": home_during > 0,
        "new_phone_signature": new_phone_signature,
        "recurring_match": bool(recurring) and trigger_type == "customer_report",
        "ring": bool(ring_cards),
        "prior_confirmed_cases": len(prior_fraud_cases),
        "account_prior_txns": len(acct),
        "clean_account": clean_account,
        "fraud_account_cases": sorted(set(acct_fraud.values())),
        "hours_to_open": round(_h(ep_rows[-1]["_t"], opened), 1),
    }

    # ---- pattern (rules verified against the closed cases' labels, see eval_analytics.py)
    if ring_cards:
        pat, why = "undocumented", "device-profile ring: several other cards used the same rare device as New"
    elif struct:
        pat, why = "undocumented", "structuring: several online purchases within an hour, each just under $500"
    elif card_testing:
        pat, why = "card_testing", ">=3 small online authorizations within an hour, then a larger purchase"
    elif channels == {"online", "in_person"}:
        pat, why = "account_takeover", "mixed in-person and online activity in one episode"
    elif channels == {"in_person"}:
        if away:
            pat, why = "out_of_region_use", f"card-present use in region {away[0]}, home region is {home}"
        else:
            pat, why = "account_takeover", f"card-present fraud inside the home region {home or '(unknown)'}"
    elif sig["new_device"]:
        pat, why = "card_not_present_new_device", "online episode with a device marked New for this account"
    else:
        pat, why = "card_not_present_fraud", "online episode, no device marked New"

    # ---- probability
    feats = {
        "logit_flag": _logit(flag["model_score"]),
        "logit_ep_max": _logit(sig["episode_max_score"]),
        "logit_ep_mean": _logit(sig["episode_mean_score"]),
        "log_ep_n": math.log(len(ep_rows)),
        "trip_signature": float(trip_signature),
        "new_phone_signature": float(new_phone_signature),
        "card_testing": float(card_testing),
        "structuring": float(bool(struct)),
        "ring": float(bool(ring_cards)),
    }
    z = cal["intercept"] + sum(cal["coef"].get(k, 0.0) * v for k, v in feats.items()) + cal["prior_shift"]
    p_model = 1 / (1 + math.exp(-z)) if cal["coef"] else flag["model_score"]
    p = p_model
    # documented overrides: sequences that are proof in themselves (README patterns 1, R9)
    hard = card_testing or struct or ring_cards
    if hard:
        p = max(p, 0.9)
    # account history, audited on Sep-Oct 2016 txns against closed cases opened before each txn:
    # an earlier txn on the account in a confirmed case -> 66% fraud in person / 82% online, 97% / 100% when
    # the bank risk score is >= 0.5 (below 0.5: 41-68% / 57-87%, so evidence only); a clean account
    # (clean_account) -> 0.17% in person, 9.9% even with risk and classifier score both >= 0.5; 0 of 451 online
    if acct_fraud and flag["risk"] >= 0.5:
        p = max(p, 0.9)
    elif clean_account and not hard:
        p = min(p, 0.15)

    # ---- evidence
    ids = lambda rows: [r["id"] for r in rows]  # noqa: E731
    pros, dfn = [], []
    hi = [r for r in ep_rows if r["model_score"] >= cal["episode_score"]]
    if flag["model_score"] >= cal["episode_score"]:
        pros.append({"claim": f"Closed-case classifier scores flagged txn {flag['id']} at {flag['model_score']:.2f} "
                              f"(learned from the bank's confirmed/cleared cases; the bank risk score "
                              f"{flag['risk']:.2f} is not used as a verdict)",
                     "score": round(flag["model_score"], 2), "entity_ids": [flag["id"]], "ref": MODEL_REF})
    else:
        dfn.append({"claim": f"Closed-case classifier scores flagged txn {flag['id']} at {flag['model_score']:.2f}, "
                             f"in line with this card's legitimate history (bank risk score {flag['risk']:.2f} "
                             f"is often high on false alarms)",
                    "score": round(1 - flag["model_score"], 2), "entity_ids": [flag["id"]], "ref": MODEL_REF})
    if len(ep_rows) > 1:
        pros.append({"claim": f"{len(ep_rows)} card txns from {ep_rows[0]['ts']} to {ep_rows[-1]['ts']} form one "
                              + ("episode (every txn this card made on the ring device)" if ring_cards else
                                 f"episode (grouped by the episode model fitted on closed cases, gaps under "
                                 f"{cal['episode_gap_h']} h)") + f", total {_usd(sum(abs(r['amount']) for r in ep_rows))}",
                     "score": round(min(0.95, 0.5 + 0.1 * len(hi)), 2), "entity_ids": ids(ep_rows), "ref": hist_ref})
    if card_testing:
        if sequence:
            rr, big, span = [txns[i] for i in run], [txns[i] for i in later_big[:4]], " within an hour"
        else:  # closed-case shape: online-only episode with a tiny authorization and a larger purchase
            rr = [r for r in ep_rows if abs(r["amount"]) < SMALL_AUTH]
            big, span = [r for r in ep_rows if abs(r["amount"]) >= 2 * SMALL_AUTH][:4], " in one online episode"
        pros.append({"claim": f"{len(rr)} online authorization(s) under {_usd(SMALL_AUTH)}{span} "
                              f"({', '.join(_usd(r['amount']) for r in rr[:6])}) then larger purchase(s) "
                              f"{', '.join(_usd(r['amount']) for r in big)}",
                     "score": 0.9, "entity_ids": ids(rr) + ids(big), "ref": hist_ref})
    if struct:
        rr = [txns[i] for i in struct]
        pros.append({"claim": f"{len(rr)} online purchases within "
                              f"{_h(rr[0]['_t'], rr[-1]['_t']) * 60:.0f} minutes, each just under $500 "
                              f"({', '.join(_usd(r['amount']) for r in rr)}): amounts kept under an authorization threshold",
                     "score": 0.9, "entity_ids": ids(rr), "ref": hist_ref})
    if ring_cards:
        pros.append({"claim": f"Device profile {device_ctx['device_id']} was used as New by {len(ring_cards)} other "
                              f"cards in the window ({ring['anon_cards']} behind an anonymous proxy); only "
                              f"{ring['ever_cards']} cards ever used it"
                              + (f"; {len(ring['cases'])} linked closed case(s) incl. {', '.join(ring['cases'][:5])}" if ring["cases"] else ""),
                     "score": 0.9, "entity_ids": ring_cards[:10] + ring["cases"],
                     "ref": f"query:device_neighbors(device_id={device_ctx['device_id']})"})
    new_rows = [r for r in ep_rows if r["dev_status"] == "New"]
    if new_rows and not new_phone_signature:
        pros.append({"claim": f"{len(new_rows)} episode txn(s) came from a device marked New for this account "
                              f"({new_rows[0]['device'] or 'profile not recorded'})"
                              + ("" if flag["device"] in prior_devices or not flag["device"]
                                 else "; the flagged device was never seen on this card before"),
                     "score": 0.6, "entity_ids": ids(new_rows[:5]), "ref": hist_ref})
    anon = [r for r in ep_rows if "ANONYMOUS" in r["proxy"]]
    if anon:
        pros.append({"claim": f"{len(anon)} episode txn(s) went through an anonymous proxy",
                     "score": 0.6, "entity_ids": ids(anon[:5]), "ref": hist_ref})
    if away and pat == "out_of_region_use":
        pros.append({"claim": f"Card-present use in billing region {away[0]}; the customer's home region is {home} "
                              f"({counts.get(away[0], 0)} earlier txns there)",
                     "score": 0.6, "entity_ids": [r["id"] for r in ep_rows if r["addr1"] in away][:5],
                     "ref": f"query:region_history(customer_id={customer_ctx.get('customer_id', 'customer')})"})
    if sig["product_new"] and flag["model_score"] >= cal["episode_score"]:
        pros.append({"claim": f"Product code {flag['product']} never used on this card in the prior window",
                     "score": 0.4, "entity_ids": [flag["id"]], "ref": hist_ref})
    if sig["amount_ratio"] and sig["amount_ratio"] >= 3 and flag["model_score"] >= cal["episode_score"]:
        pros.append({"claim": f"Flagged amount {_usd(flag['amount'])} is {sig['amount_ratio']:.1f}x the card's median "
                              f"{_usd(med)}", "score": 0.4, "entity_ids": [flag["id"]], "ref": hist_ref})
    if prior_fraud_cases:
        pros.append({"claim": f"Customer has {len(prior_fraud_cases)} earlier confirmed fraud case(s): "
                              f"{', '.join(prior_fraud_cases[:5])}", "score": 0.4,
                     "entity_ids": prior_fraud_cases[:5], "ref": "query:customer_cases"})
    acct_desc = (f"the same underlying account as flagged txn {flag['id']} (billing region {flag['addr1']}, account first "
                 f"seen {(flag['_t'] - timedelta(days=flag['d1'] or 0)).date()} = txn date minus D1, within a day)")
    if acct_fraud:
        fc = sorted(set(acct_fraud.values()))
        pros.append({"claim": f"Earlier txn(s) {', '.join(list(acct_fraud)[:6])} on {acct_desc} are in confirmed fraud "
                              f"case(s) {', '.join(fc)}; in the bank's Sep-Oct history 66% of in-person (82% online) txns "
                              f"on such an account were fraud, 97% when the bank risk score was >= 0.50 "
                              f"(here {flag['risk']:.2f})",
                     "score": 0.9 if flag["risk"] >= 0.5 else 0.6, "entity_ids": fc + list(acct_fraud)[:6],
                     "ref": "query:customer_cases + get_neighbors(ClosedCase-INVOLVES-Txn)"})
    if clean_account:
        dfn.append({"claim": f"{len(acct_old)} txns on {acct_desc}, from {acct_old[0]['ts'][:10]} to "
                             f"{acct_old[-1]['ts'][:10]} (at least {CLEAN_ACCOUNT_DAYS} days before the flag), and none "
                             f"of its txns is in any closed case; in the bank's Sep-Oct history 0.17% of in-person txns on "
                             f"such an account were fraud (9.9% even when risk and classifier scores were both >= 0.50)",
                    "score": 0.8, "entity_ids": ids(acct_old[-10:]), "ref": hist_ref})
    if trip_signature:
        dfn.append({"claim": f"Card-present purchases in region {trip_region} on {len(trip_days)} different days "
                             f"while {home_during} txns continued in home region {home}: looks like a trip, not a clone",
                    "score": 0.7, "entity_ids": [r["id"] for r in txns if r["addr1"] == trip_region][:6],
                    "ref": f"query:region_history(customer_id={customer_ctx.get('customer_id', 'customer')})"})
    if new_phone_signature:
        dfn.append({"claim": f"Device {flag['device']} is New but was then used again on this card "
                             f"({len(same_dev)} txns, all scored low): consistent with the cardholder's new phone",
                    "score": 0.6, "entity_ids": [flag["id"]] + ids(same_dev[:4]), "ref": hist_ref})
    elif flag["device"] and flag["device"] in prior_devices:
        dfn.append({"claim": f"Flagged device {flag['device']} was already used on this card before",
                    "score": 0.5, "entity_ids": [flag["id"]], "ref": hist_ref})
    if recurring:
        dfn.append({"claim": f"Disputed {_usd(flag['amount'])} ({flag['product']}) matches earlier charges of the same "
                             f"amount and product roughly monthly: {', '.join(recurring[:4])}",
                    "score": 0.8, "entity_ids": [flag["id"]] + recurring[:4], "ref": hist_ref})
    if flag["channel"] == "in_person" and flag["addr1"] and flag["addr1"] == home:
        dfn.append({"claim": f"Flagged purchase is in the customer's home region {home}",
                    "score": 0.3, "entity_ids": [flag["id"]], "ref": hist_ref})

    # ---- verdict (§6: decisive only with >= 2 independent pieces of evidence)
    p = round(min(max(p, 0.01), 0.99), 3)
    strong_p = [e for e in pros if e["score"] >= 0.5]
    strong_d = [e for e in dfn if e["score"] >= 0.5]
    if p >= 0.5:
        n_ind = len({e["ref"].split("(")[0] + e["claim"][:12] for e in pros})
    else:
        n_ind = len({e["ref"].split("(")[0] + e["claim"][:12] for e in dfn})
    if p >= cal["fraud_at"] and n_ind >= 2:
        verdict = "fraud"
    elif p <= cal["legit_at"] and n_ind >= 2:
        verdict = "legitimate"
    else:
        verdict = "uncertain"
    if recurring and trigger_type == "customer_report" and p < cal["fraud_at"]:
        verdict = "legitimate" if p <= 0.5 else "uncertain"

    # R6 shared origin on a rare device: only when the card's own evidence already leans fraud, and after the
    # verdict, so it never changes probability, verdict or the independent-evidence count
    shared_cards, shared_txns = [], []
    if not ring_cards and p >= 0.5 and verdict != "legitimate":
        exclude = set(customer_ctx.get("cards") or []) | {customer_ctx.get("card_id")}
        shared_cards, shared_txns = _shared_origin(device_ctx, flag, opened, exclude)
    if shared_cards:
        pros.append({"claim": f"Device profile {flag['device']} (only {device_ctx['ever_cards']} cards ever) with "
                              f"purchaser/recipient email {flag['p_email']} -> {flag['r_email']} was also used by "
                              f"{len(shared_cards)} other card(s) from 7 days before the flag up to opening: "
                              + ", ".join(f"{r['card_id']} (txn {r['id']}, {r['ts']})" for r in shared_txns[:6])
                              + "; in the bank's Aug-Oct history 48% of such matches were confirmed fraud vs 11% without",
                     "score": 0.6, "entity_ids": shared_cards[:10] + [r["id"] for r in shared_txns[:10]],
                     "ref": f"query:device_neighbors(device_id={flag['device']}) + query:card_history(other cards, 7d)"})
    link_cards = ring_cards or shared_cards

    fraud_ep = verdict != "legitimate"
    out_rows = ep_rows if fraud_ep else []
    return {
        "episode": {
            "affected_txn_ids": ids(out_rows),
            "first_suspicious_txn_id": out_rows[0]["id"] if out_rows else "",
            "exposure_usd": round(sum(abs(r["amount"]) for r in out_rows), 2),
        },
        "candidate_txn_ids": ids(ep_rows),
        "signals": sig,
        "features": {k: round(v, 4) for k, v in feats.items()},
        "pattern": pat if verdict != "legitimate" else "none",
        "raw_pattern": pat,
        "pattern_reason": why if verdict != "legitimate" else "activity judged legitimate",
        "prosecution": pros,
        "defence": dfn,
        "fraud_probability": p,
        "model_probability": round(p_model, 3),
        "verdict": verdict,
        "independent_evidence": n_ind,
        "single_signal": len(strong_p if p >= 0.5 else strong_d) <= 1,
        "evidence_conflicts": bool(strong_p) and bool(strong_d) and 0.3 < p < 0.85,
        "card_testing": card_testing,
        "cleared_purchase_over_100": sig["cleared_purchase_over_100"],
        "recurring_match": sig["recurring_match"],
        "shared_origin": ({"kind": "device", "id": device_ctx["device_id"], "card_ids": link_cards}
                          if link_cards else None),
        "connects_to_other_fraud": bool(ring_cards) and bool(ring and ring["cases"]) or bool(ring_cards),
        "connected_card_ids": link_cards,
        "connected_device_profiles": [device_ctx["device_id"]] if link_cards else [],
    }
