"""Replay the bank's closed cases through hhg.analytics.assess and calibrate it.

For each closed case we rebuild what the agent would see at opened_at: the card's txns in
[opened_at - 60 d, opened_at] (card = customer + card4 + card6), the flagged txn (cleared: the case txn;
confirmed: a random case txn, or the last one with --flag last), customer-wide billing-region counts,
earlier closed cases of the customer, and the device_neighbors view of the flagged device.
Fit on cases opened Jul-Aug, report on the September holdout.
Writes data_prep/calibration.json (unless --no-write).

Usage: PYTHONPATH=src python scripts/eval_analytics.py [--flag random|last] [--no-write] [--no-fit]
       [--cache DIR] (reuse rebuilt inputs) [--dump FILE] (holdout rows, for error analysis)
"""
import bisect
import json
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from hhg import analytics

ROOT = Path(__file__).resolve().parents[1]
PREP, DATA = ROOT / "data_prep", ROOT / "dataset"
SPLIT, END = "2016-09-01", "2016-10-01 20:00:00"   # partial.pkl ends 2016-10-01
# trip_signature is not a feature: as coded it fires on 71% of confirmed out_of_region_use and 8% of cleared
# travel cases (the closed-case travel notes are templated), so a fit would read a "trip" as fraud
FEATS = ["logit_flag", "logit_ep_max", "logit_ep_mean", "log_ep_n", "new_phone_signature"]


def code(x):
    return "" if pd.isna(x) else f"{float(x):.1f}"


def load_raw():
    """Jul - END transactions with the columns the replay needs, cached in data_prep/partial.pkl."""
    if (PREP / "partial.pkl").exists():
        return pd.read_pickle(PREP / "partial.pkl")
    cols = ["TransactionID", "TransactionAmt", "ProductCD", "card4", "card6", "addr1", "addr2", "dist1",
            "P_emaildomain", "R_emaildomain", "C1", "C13", "D1", "D15", "M4", "M6", "customer_id", "ts", "channel",
            "risk_score"]
    tx = pd.read_csv(ROOT / "_dl" / "transactions.csv", usecols=cols, dtype={"TransactionID": str})
    tx = tx[tx["ts"] <= END]
    idn = pd.read_csv(DATA / "identity.csv", dtype=str, usecols=["TransactionID", "id_15", "id_23", "id_30", "id_31",
                                                                 "id_33", "DeviceType", "DeviceInfo"])
    tx = tx.merge(idn, on="TransactionID", how="left")
    tx["ts"] = pd.to_datetime(tx["ts"])
    tx["dev"] = tx[["DeviceInfo", "id_30", "id_31", "id_33"]].fillna("").agg(" | ".join, axis=1)
    tx.loc[tx["dev"] == " |  |  | ", "dev"] = ""
    tx.to_pickle(PREP / "partial.pkl")
    return tx


def load():
    tx = load_raw()
    tx = tx.merge(pd.read_parquet(PREP / "txn_scores.parquet"), on="TransactionID", how="left")
    tx["card"] = tx["customer_id"] + "|" + tx["card4"].fillna("") + "|" + tx["card6"].fillna("")
    cc = pd.read_csv(DATA / "closed_cases_history.csv", dtype=str).fillna("")
    # case card ids come from the case txns ((customer, card4, card6) is an exact partition; the K-number is not derivable)
    k = {t: c.card_id for c in cc.itertuples() for t in c.txn_ids.split("|")}
    m = tx.assign(k=tx["TransactionID"].map(k)).dropna(subset=["k"]).drop_duplicates("card").set_index("card")["k"]
    tx["cid"] = tx["card"].map(m).fillna(tx["card"])
    tx = tx.sort_values("ts").reset_index(drop=True)
    tx["ts_s"] = tx["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    tx["a1"] = tx["addr1"].map(code)
    return tx, cc


def records(g):
    return pd.DataFrame({
        "id": g["TransactionID"], "ts": g["ts_s"], "amount": g["TransactionAmt"].round(2), "product": g["ProductCD"],
        "channel": g["channel"], "risk": g["risk_score"], "addr1": g["a1"], "addr2": g["addr2"].map(code),
        "dist1": g["dist1"].fillna(-1), "p_email": g["P_emaildomain"].fillna(""), "r_email": g["R_emaildomain"].fillna(""),
        "m_flags": "|||" + g["M4"].fillna("") + "||" + g["M6"].fillna("") + "|||",
        "c1": g["C1"].fillna(-1), "c13": g["C13"].fillna(-1), "d1": g["D1"].fillna(-1), "d15": g["D15"].fillna(-1),
        "model_score": g["model_score"].round(4), "device": g["dev"].fillna(""), "dev_status": g["id_15"].fillna(""),
        "proxy": g["id_23"].fillna(""),
    }).to_dict("records")


def build_inputs(tx, cc, flag_mode, seed=0):
    rng = random.Random(seed)
    cc = cc[(cc["opened_at"] <= END)]
    cards = {k: records(g) for k, g in tx[tx["cid"].isin(set(cc["card_id"]))].groupby("cid", sort=False)}
    cts = {k: [r["ts"] for r in v] for k, v in cards.items()}
    cust = {k: (g["ts_s"].tolist(), g["a1"].tolist()) for k, g in tx.groupby("customer_id", sort=False)}
    dv = tx[tx["dev"] != ""]
    devs = {k: (g["ts_s"].tolist(), g["cid"].tolist(), g["TransactionID"].tolist(), g["id_15"].fillna("").tolist(),
                g["id_23"].fillna("").tolist()) for k, g in dv.groupby("dev", sort=False)}
    dev_of = dict(zip(dv["TransactionID"], dv["dev"]))
    case_of_txn = {}
    for c in cc.itertuples():
        for t in c.txn_ids.split("|"):
            case_of_txn[t] = (c.case_id, c.closed_at, c.outcome)
    by_cust = defaultdict(list)
    for c in cc.itertuples():
        by_cust[c.customer_id].append(c)
    out = []
    for c in cc.itertuples():
        truth = c.txn_ids.split("|")
        h = cards.get(c.card_id)
        if h is None:
            continue
        have = {r["id"] for r in h}
        if not all(t in have for t in truth):
            continue
        lo = str(pd.Timestamp(c.opened_at) - pd.Timedelta(days=60))
        w = h[bisect.bisect_left(cts[c.card_id], lo):bisect.bisect_right(cts[c.card_id], c.opened_at)]
        if not all(t in {r["id"] for r in w} for t in truth):
            continue
        if c.outcome == "cleared":
            flag = truth[0]
        else:
            order = [r["id"] for r in w if r["id"] in set(truth)]
            flag = order[-1] if flag_mode == "last" else rng.choice(order)
        ts, a1 = cust[c.customer_id]
        rc = Counter(a for a in a1[:bisect.bisect_right(ts, c.opened_at)] if a)
        prior_cases = [{"id": p.case_id, "outcome": p.outcome, "pattern": p.pattern} for p in by_cust[c.customer_id]
                       if p.closed_at < c.opened_at]
        ctx = {"card_id": c.card_id, "customer_id": c.customer_id, "region_counts": dict(rc), "cases": prior_cases}
        dctx = None
        d = dev_of.get(flag)
        if d:
            dts, dcid, did, dnew, dprox = devs[d]
            end = bisect.bisect_right(dts, c.opened_at)
            start = bisect.bisect_left(dts, str(pd.Timestamp(c.opened_at) - pd.Timedelta(days=30)))
            ever = len(set(dcid[:end]))
            agg = {}
            for i in range(start, end):
                a = agg.setdefault(dcid[i], {"id": dcid[i], "n": 0, "n_new": 0, "txns": [], "proxy": [], "cases": []})
                a["n"] += 1
                a["n_new"] += dnew[i] == "New"
                a["txns"].append(did[i])
                a["proxy"].append(dprox[i])
                k = case_of_txn.get(did[i])
                if k and k[1] < c.opened_at and k[2] == "confirmed_fraud" and k[0] not in a["cases"]:
                    a["cases"].append(k[0])
            dctx = {"device_id": d, "ever_txns": end, "ever_cards": ever, "cards": list(agg.values())[:200]}
        out.append({"case": c.case_id, "outcome": c.outcome, "pattern": c.pattern, "opened_at": c.opened_at,
                    "truth": truth, "first": c.first_fraud_txn_id, "exposure": float(c.exposure_usd or 0), "flag": flag, "txns": w,
                    "ctx": ctx, "dctx": dctx, "notes": c.analyst_notes})
    return out


def run(inputs, cal):
    rows = []
    for x in inputs:
        trig = "risk_score" if x["outcome"] == "cleared" else "customer_report"
        a = analytics.assess(x["txns"], x["flag"], x["opened_at"], trig, x["dctx"], x["ctx"], cal=cal)
        y = int(x["outcome"] == "confirmed_fraud")
        cand = set(a["candidate_txn_ids"])
        got = set(a["episode"]["affected_txn_ids"])
        truth = set(x["truth"]) if y else set()
        jac = lambda p, t: len(p & t) / len(p | t) if p | t else 1.0  # noqa: E731
        rows.append({"case": x["case"], "y": y, "month": x["opened_at"][:7], "true_pat": x["pattern"],
                     "pat": a["pattern"], "raw_pat": a["raw_pattern"], "p": a["fraud_probability"],
                     "p_model": a["model_probability"], "verdict": a["verdict"], "n_ind": a["independent_evidence"],
                     "jac_raw": jac(cand, set(x["truth"])) if y else np.nan, "jac": jac(got, truth),
                     "first_ok": (a["candidate_txn_ids"][0] == x["first"]) if y else np.nan,
                     "exp_err": abs(a["episode"]["exposure_usd"] - (x["exposure"] if y else 0)),
                     "cleared_reason": x["notes"].split(". ")[1][:40] if not y else "",
                     **a["features"], **{k: v for k, v in a["signals"].items() if not isinstance(v, str)}})
    return pd.DataFrame(rows)


def fit(df):
    X, y = df[FEATS].to_numpy(float), df["y"].to_numpy()
    m = LogisticRegression(C=1.0, max_iter=2000).fit(X, y)
    base = y.mean()
    shift = float(np.log(0.5 / 0.5) - np.log(base / (1 - base)))
    return {k: round(float(v), 4) for k, v in zip(FEATS, m.coef_[0])}, round(float(m.intercept_[0]), 4), round(shift, 4)


def weights(df):
    # re-weight to the exam's 50/50 prior
    n1, n0 = (df["y"] == 1).sum(), (df["y"] == 0).sum()
    return np.where(df["y"] == 1, 0.5 / n1, 0.5 / n0)


def report(df, title):
    w = weights(df)
    print(f"\n=== {title}: {len(df)} cases ({df['y'].sum()} confirmed, {(1 - df['y']).sum()} cleared)")
    pred = (df["p"] >= 0.5).astype(int)
    print(f"binary accuracy p>=0.5: raw {np.mean(pred == df['y']):.3f}, at 50/50 prior {np.sum(w * (pred == df['y'])):.3f}")
    vt = df["verdict"].map({"fraud": 1, "legitimate": 0})
    dec = vt.notna()
    print("verdict bands:", df["verdict"].value_counts().to_dict(),
          f"| decided accuracy {np.mean(vt[dec] == df['y'][dec]):.3f}",
          f"| decided accuracy 50/50 {np.sum(w[dec] * (vt[dec] == df['y'][dec])) / np.sum(w[dec]):.3f}")
    print(pd.crosstab(df["verdict"], df["y"].map({1: "confirmed", 0: "cleared"})).to_string())
    print(f"Brier (50/50 weighted) {np.sum(w * (df['p'] - df['y']) ** 2):.4f}; raw {np.mean((df['p'] - df['y']) ** 2):.4f}")
    bins = pd.cut(df["p"], [0, .05, .15, .3, .5, .7, .85, .95, 1.0], include_lowest=True)
    rel = pd.DataFrame({"bin": bins, "y": df["y"], "w": w}).groupby("bin", observed=True).apply(
        lambda g: pd.Series({"n": len(g), "frac_fraud_50_50": np.sum(g.w * g.y) / np.sum(g.w)}), include_groups=False)
    print("reliability (50/50 weighted):\n" + rel.round(3).to_string())
    f = df[df["y"] == 1]
    print(f"episodes (confirmed): Jaccard raw {f['jac_raw'].mean():.3f} final {f['jac'].mean():.3f}; "
          f"first_suspicious (raw) ok {f['first_ok'].mean():.3f}; exposure abs err median {f['exp_err'].median():.2f} "
          f"mean {f['exp_err'].mean():.2f}")
    print(f"cleared: empty-episode rate {(df[df['y'] == 0]['jac'] == 1).mean():.3f}")
    print("Jaccard by pattern:", f.groupby("true_pat")["jac_raw"].mean().round(3).to_dict())
    print(f"pattern accuracy (final, all cases) {np.mean(df['pat'] == df['true_pat']):.3f}; "
          f"raw pattern on confirmed {np.mean(f['raw_pat'] == f['true_pat']):.3f}")
    print(pd.crosstab(f["true_pat"], f["raw_pat"]).to_string())


def fit_members(train):
    """Episode membership: logistic regression on (card txn, flagged txn) pairs from confirmed cases."""
    X, y = [], []
    for x in train:
        if x["outcome"] == "cleared":
            continue
        rows = [dict(r, _t=analytics._t(r["ts"])) for r in x["txns"]]
        f = next(r for r in rows if r["id"] == x["flag"])
        truth = set(x["truth"])
        for r in rows:
            if r is not f and abs(analytics._h(f["_t"], r["_t"])) <= 24 * analytics.DEFAULT_CAL["episode_days"]:
                X.append(analytics.member_features(r, f))
                y.append(r["id"] in truth)
    m = LogisticRegression(max_iter=5000).fit(np.array(X, float), np.array(y))
    return [round(float(v), 4) for v in m.coef_[0]], round(float(m.intercept_[0]), 4)


def get_inputs(flag_mode):
    cache = sys.argv[sys.argv.index("--cache") + 1] + f"/inputs_{flag_mode}.pkl" if "--cache" in sys.argv else None
    if cache and Path(cache).exists():
        return pickle.load(open(cache, "rb"))
    tx, cc = load()
    inputs = build_inputs(tx, cc, flag_mode)
    if cache:
        pickle.dump(inputs, open(cache, "wb"))
    return inputs


def main():
    flag_mode = "last" if "--flag" in sys.argv and sys.argv[sys.argv.index("--flag") + 1] == "last" else "random"
    inputs = get_inputs(flag_mode)
    train = [x for x in inputs if x["opened_at"] < SPLIT]
    test = [x for x in inputs if x["opened_at"] >= SPLIT]
    cal = analytics.load_calibration()
    if "--no-fit" not in sys.argv:
        coef, icpt = fit_members(train)
        cal = {**analytics.DEFAULT_CAL, "member_coef": coef, "member_intercept": icpt}
        conf = [x for x in train if x["outcome"] != "cleared"]
        best = None
        for tau in (0.2, 0.3, 0.4, 0.5):
            j = run(conf, {**cal, "member_tau": tau})["jac_raw"].mean()
            print(f"member_tau {tau}: train Jaccard {j:.3f}")
            best = max(best or (j, tau), (j, tau))
        cal["member_tau"] = best[1]
        d = run(train, cal)
        coef, icpt, shift = fit(d)
        cal.update(coef=coef, intercept=icpt, prior_shift=shift, fit_on=f"{len(d)} closed cases opened before {SPLIT}",
                   train_base_rate=round(float(d["y"].mean()), 4))
        print("calibration:", json.dumps(cal))
        if "--no-write" not in sys.argv:
            (PREP / "calibration.json").write_text(json.dumps(cal, indent=2))
    report(run(train, cal), f"TRAIN Jul-Aug (flag={flag_mode})")
    te = run(test, cal)
    report(te, f"HOLDOUT Sep (flag={flag_mode})")
    if "--dump" in sys.argv:  # e.g. to a scratch dir, for error analysis
        te.to_pickle(sys.argv[sys.argv.index("--dump") + 1])


if __name__ == "__main__":
    main()
