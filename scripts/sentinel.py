"""Sentinel mode: watch the exam period (Nov-Dec 2016) on the graph, raise alerts beyond the 20 case-pack
cases, and investigate each with the same agent. README: "If your agent also monitors the exam period on its
own ... put those in a separate folder." Output: sentinel_cases/SEN-0xx.json, traces/, SUMMARY.md.

Alert sources (all through mcp_tools.run_query, i.e. the TigerGraph MCP server):
  device_ring  device_ring_scan in rolling 30-day windows; profiles used as New by >60 cards are common
               devices, not rings; the rest (anonymous-proxy first) are confirmed with device_neighbors and
               analytics._ring, the same rarity rule the agent applies (rare profile, most of its users are
               new to it in the window, anonymous proxy or earlier cases).
  structuring  near_threshold_scan $450-$500 online, >=3 txns on one card within 60 minutes.
  model_score  cards surfaced by the device scan (anonymous-proxy devices first) whose card_history holds
               >=2 txns within 48 h scored >=0.90 by the closed-case classifier (Txn.model_score). The
               bank's own risk score is inverted among alerts and is never used.

Usage: PYTHONPATH=src python scripts/sentinel.py [--dry-run] [--max N]
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timedelta

from hhg import analytics, config, mcp_tools

START, END = datetime(2016, 11, 1), datetime(2016, 12, 31, 23, 59, 59)
WINDOW, STEP = timedelta(days=30), timedelta(days=15)
RING_MIN_CARDS, RING_MAX_CARDS, RING_PROBES = 3, 60, 8
STRUCT_LO, STRUCT_HI, STRUCT_MIN_TXNS, STRUCT_SPAN = 450, 500, 3, timedelta(minutes=60)
SCORE_MIN, SCORE_BURST, SCORE_PROBES = 0.90, timedelta(hours=48), 10
MAX_ALERTS = 15
OPEN_DELAY = timedelta(hours=2)
OUT = config.ROOT / "sentinel_cases"
FMT = "%Y-%m-%d %H:%M:%S"


def _ts(s):
    return datetime.strptime(s[:19], FMT)


def _fmt(d):
    return d.strftime(FMT)


def case_pack_cards():
    with open(config.DATASET / "case_pack.csv", newline="", encoding="utf-8") as f:
        return {r["card_id"] for r in csv.DictReader(f)}


def windows():
    """Rolling 30-day windows, 15-day step, clipped to END."""
    out, s = [], START
    while True:
        e = min(s + WINDOW - timedelta(seconds=1), END)
        out.append((s, e))
        if e == END:
            return out
        s += STEP


def _anon(proxies):
    return any("ANONYMOUS" in (p or "") for p in proxies)


# ---------------------------------------------------------------- device rings

def ring_candidates():
    """Devices used as New by >=3 cards in any window, merged across windows; common profiles dropped;
    anonymous-proxy devices first, then by number of cards."""
    devs = {}
    for a, b in windows():
        res = mcp_tools.run_query("device_ring_scan", {"t_from": _fmt(a), "t_to": _fmt(b), "min_cards": RING_MIN_CARDS})
        for v in res.get("devices", []):
            x = v["attributes"]
            d = devs.setdefault(v["v_id"], {"id": v["v_id"], "cards": set(), "proxies": set(), "t_from": a, "t_to": b})
            d["cards"] |= set(x.get("@new_cards", []))
            d["proxies"] |= set(x.get("@proxies", []))
            d["t_from"], d["t_to"] = min(d["t_from"], a), max(d["t_to"], b)
    keep = [d for d in devs.values() if len(d["cards"]) <= RING_MAX_CARDS]
    return sorted(keep, key=lambda d: (not _anon(d["proxies"]), -len(d["cards"]), d["id"]))


def device_ctx(device_id, t_from, t_to):
    """device_neighbors result in the shape analytics expects."""
    r = mcp_tools.run_query("device_neighbors", {"device_id": device_id, "t_from": _fmt(t_from), "t_to": _fmt(t_to)})
    cards = [{"id": v["v_id"], **{k[1:]: val for k, val in v["attributes"].items() if k.startswith("@")}}
             for v in r.get("cards", [])]
    return {"device_id": device_id, "ever_txns": r.get("ever_txns", 0), "ever_cards": r.get("ever_cards", 0),
            "cards": cards}


def _txn_at(card_id, ts, candidates):
    """ID of the card's txn at timestamp ts (preferring one of `candidates`)."""
    txns = [v["v_id"] for v in mcp_tools.run_query("card_history", {"card_id": card_id, "t_from": ts, "t_to": ts})["txns"]]
    return next((t for t in txns if t in candidates), txns[0] if txns else None)


def ring_alerts(devs, excluded):
    alerts = []
    for d in devs[:RING_PROBES]:
        ctx = device_ctx(d["id"], d["t_from"], d["t_to"])
        ring_cards, info = analytics._ring(ctx, set())
        by_id = {c["id"]: c for c in ctx["cards"]}
        subjects = [by_id[c] for c in ring_cards if c not in excluded and c not in {a["card_id"] for a in alerts}]
        if not subjects:
            continue
        subj = max(subjects, key=lambda c: (c["last"], c["id"]))  # most recent ring card opens the case
        flag = _txn_at(subj["id"], subj["last"], set(subj.get("txns") or []))
        if not flag:
            continue
        first = min(c["first"] for c in ctx["cards"] if c["id"] in ring_cards)
        in_pack = sorted(set(ring_cards) & excluded)
        signal = f"device {d['id']} New on {len(ring_cards)} cards ({info['anon_cards']} anon proxy), {info['ever_cards']} ever"
        text = (f"Sentinel sweep (device_ring_scan): device profile {d['id']} was used as New by {len(ring_cards)} "
                f"cards between {first[:10]} and {subj['last'][:10]} ({info['anon_cards']} behind an anonymous proxy); "
                f"only {info['ever_cards']} cards ever used it"
                + (f"; linked cases {', '.join(info['cases'][:5])}" if info["cases"] else "")
                + (f"; ring also touches case-pack card(s) {', '.join(in_pack)}" if in_pack else "")
                + f". Review transaction {flag} on card {subj['id']} and look for related activity.")
        alerts.append({"source": "device_ring", "card_id": subj["id"], "flagged_txn_id": flag,
                       "last_ts": subj["last"], "signal": signal, "trigger_text": text})
    return alerts


# ---------------------------------------------------------------- structuring

def structuring_alerts(excluded):
    res = mcp_tools.run_query("near_threshold_scan", {"t_from": _fmt(START), "t_to": _fmt(END), "lo": STRUCT_LO,
                                                      "hi": STRUCT_HI, "min_txns": STRUCT_MIN_TXNS})
    alerts = []
    for v in res.get("cards", []):
        if v["v_id"] in excluded:
            continue
        x = v["attributes"]
        tx = sorted(zip(map(_ts, x["@times"]), x["@txns"]))  # the two ListAccums are filled in the same ACCUM
        best = []
        for i in range(len(tx)):
            grp = [t for t in tx[i:] if t[0] - tx[i][0] <= STRUCT_SPAN]
            if len(grp) > len(best):
                best = grp
        if len(best) < STRUCT_MIN_TXNS:
            continue
        mins = round((best[-1][0] - best[0][0]).total_seconds() / 60)
        ids = [t[1] for t in best]
        alerts.append({
            "source": "structuring", "card_id": v["v_id"], "flagged_txn_id": ids[-1], "last_ts": _fmt(best[-1][0]),
            "signal": f"{len(ids)} online txns ${STRUCT_LO}-${STRUCT_HI} in {mins} min",
            "trigger_text": (f"Sentinel sweep (near_threshold_scan): card {v['v_id']} made {len(ids)} online purchases "
                             f"between ${STRUCT_LO} and ${STRUCT_HI} within {mins} minutes on {best[0][0]:%Y-%m-%d} "
                             f"(transactions {', '.join(ids)}), amounts kept just under a $500 threshold. "
                             f"Review transaction {ids[-1]} and look for related activity.")})
    return alerts


# ---------------------------------------------------------------- model score

def score_alerts(cards):
    alerts = []
    for card in cards[:SCORE_PROBES]:
        res = mcp_tools.run_query("card_history", {"card_id": card, "t_from": _fmt(START), "t_to": _fmt(END)})
        hi = [v["attributes"] for v in res.get("txns", []) if (v["attributes"].get("model_score") or 0) >= SCORE_MIN]
        if not hi:
            continue
        top = max(hi, key=lambda t: (t["model_score"], t["ts"]))
        burst = sorted((t for t in hi if abs(_ts(t["ts"]) - _ts(top["ts"])) <= SCORE_BURST), key=lambda t: t["ts"])
        if len(burst) < 2:
            continue
        ids = [t["id"] for t in burst]
        alerts.append({
            "source": "model_score", "card_id": card, "flagged_txn_id": top["id"], "last_ts": burst[-1]["ts"],
            "signal": f"{len(ids)} txns scored >={SCORE_MIN:.2f} within 48 h (max {top['model_score']:.2f})",
            "trigger_text": (f"Sentinel sweep (model_score): the closed-case classifier scored {len(ids)} transactions on "
                             f"card {card} at {SCORE_MIN:.2f} or above within 48 hours ({', '.join(ids[:8])}); "
                             f"highest {top['model_score']:.2f} on transaction {top['id']} (${top['amount']:,.2f}, "
                             f"{top['channel']}). The card surfaced in the device scan. Review transaction {top['id']} "
                             f"and look for related activity.")})
    return alerts


# ---------------------------------------------------------------- sweep + run

def sweep(max_alerts=MAX_ALERTS):
    excluded = case_pack_cards()
    devs = ring_candidates()
    alerts = ring_alerts(devs, excluded)
    alerts += structuring_alerts(excluded | {a["card_id"] for a in alerts})
    if len(alerts) < max_alerts:
        seen = excluded | {a["card_id"] for a in alerts}
        pool = list(dict.fromkeys(c for d in devs for c in sorted(d["cards"]) if c not in seen))
        alerts += score_alerts(pool)
    return alerts[:max_alerts]


def case_row(alert, n):
    return {"case_id": f"SEN-{n:03d}", "opened_at": _fmt(_ts(alert["last_ts"]) + OPEN_DELAY),
            "trigger_type": "analyst_request", "trigger_text": alert["trigger_text"],
            "flagged_txn_id": alert["flagged_txn_id"], "card_id": alert["card_id"],
            "customer_id": alert["card_id"].split("-")[0], "risk_score": ""}


def run(alerts):
    from hhg import agent  # imported late: --dry-run needs no LLM
    (OUT / "traces").mkdir(parents=True, exist_ok=True)
    rows = []
    for n, alert in enumerate(alerts, 1):
        row = case_row(alert, n)
        print(f"{row['case_id']} {alert['source']} {row['card_id']} ...", flush=True)
        try:
            answer, trace = agent.investigate(row, write_graph=True)
        except Exception as e:  # one failing case (quota, graph hiccup) must not stop the sweep
            print(f"  failed: {e}", file=sys.stderr)
            rows.append([row["case_id"], alert["source"], row["card_id"], alert["signal"], "error", "", "", "", str(e)[:80]])
            continue
        (OUT / f"{row['case_id']}.json").write_text(json.dumps(answer, indent=2), encoding="utf-8")
        (OUT / "traces" / f"{row['case_id']}.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        c = answer["case"]
        acts = ", ".join(f"{a['action']} ({a['route']})" for a in answer["next_best_actions"]["final"])
        rows.append([row["case_id"], alert["source"], row["card_id"], alert["signal"], c["verdict"], c["pattern"],
                     f"{c['fraud_probability']:.2f}", f"${c['exposure_usd']:,.2f}", acts])
    write_summary(rows)


def write_summary(rows):
    head = ["Case", "Alert source", "Card", "Signal", "Verdict", "Pattern", "p", "Exposure", "Final actions"]
    lines = ["# Sentinel cases", "",
             f"Autonomous sweep of {START:%Y-%m-%d} to {END:%Y-%m-%d} over TigerGraph (via MCP), outside the 20 "
             f"case-pack cards. Signals: device rings (device_ring_scan, 30-day windows, >= {RING_MIN_CARDS} cards New "
             f"on a rare profile, <= {RING_MAX_CARDS} cards), structuring (near_threshold_scan ${STRUCT_LO}-${STRUCT_HI}, "
             f">= {STRUCT_MIN_TXNS} online txns within 60 min), model score (>= 2 txns scored >= {SCORE_MIN:.2f} by the "
             f"closed-case classifier within 48 h). Each alert is investigated by the same agent as the case pack.", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(x).replace("|", "/") for x in r) + " |" for r in rows]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="list alerts only")
    ap.add_argument("--max", type=int, default=MAX_ALERTS)
    args = ap.parse_args()
    alerts = sweep(args.max)
    for n, a in enumerate(alerts, 1):
        r = case_row(a, n)
        print(f"{r['case_id']}  {a['source']:<12} {r['card_id']:<11} txn {r['flagged_txn_id']:<8} "
              f"opened {r['opened_at']}  {a['signal']}")
    if not alerts:
        print("no alerts")
    if not args.dry_run and alerts:
        run(alerts)


if __name__ == "__main__":
    main()
