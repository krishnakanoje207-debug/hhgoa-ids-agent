"""Transaction fraud model learned from the bank's own closed cases (README: "your labeled history").

Labels: txns in confirmed_fraud cases = 1; txns in cleared cases = 0; plus a 15% sample of all other Jul-Oct
txns = 0. The closed cases hold about all the fraud, so unlabelled txns are mostly legitimate, including
those on cards that have cases; excluding those cards taught the model "card has case history" = fraud.
Features: Vesta's anonymous C/D/M/V/id columns + amount/product/card/email/device fields, and the
bank's risk score. Never uses the public Kaggle files.
Validation is a time split: train on cases opened Jul-Aug, test on Sep-Oct.
Output: data_prep/txn_scores.parquet (a fraud score for every txn; out-of-fold for labelled txns) and data_prep/model_report.json.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from hhg import config

RAW = sys.argv[1] if len(sys.argv) > 1 else str(config.ROOT / "_dl" / "transactions.csv")
CAT = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain", "M1", "M2", "M3", "M4", "M5", "M6",
       "M7", "M8", "M9", "id_12", "id_15", "id_16", "id_23", "id_27", "id_28", "id_29", "id_30", "id_31",
       "id_34", "id_35", "id_36", "id_37", "id_38", "DeviceType", "DeviceInfo", "channel"]
DROP = ["TransactionID", "TransactionDT", "customer_id", "ts", "card1"]
F32 = {**{f"V{i}": "float32" for i in range(1, 340)}, **{f"C{i}": "float32" for i in range(1, 15)},
       **{f"D{i}": "float32" for i in range(1, 16)}}  # halves memory on a 7 GB machine


def load():
    if RAW.endswith(".part"):  # partial download: cut the last incomplete line
        import io
        raw = open(RAW, "rb").read()
        tx = pd.read_csv(io.BytesIO(raw[:raw.rfind(b"\n") + 1]), dtype={"TransactionID": str, **F32})
    else:
        tx = pd.read_csv(RAW, dtype={"TransactionID": str, **F32})
    ident = pd.read_csv(config.DATASET / "identity.csv", dtype={"TransactionID": str})
    tx = tx.merge(ident, on="TransactionID", how="left")
    tx["ts"] = pd.to_datetime(tx["ts"])
    return tx


def features(tx):
    X = tx.drop(columns=[c for c in DROP if c in tx])
    for c in CAT:  # the model takes at most 255 categories: keep the most common, lump the rest
        top = X[c].value_counts().index[:250]
        X[c] = X[c].where(X[c].isin(top), "other").astype("category")
    text = [c for c in X.columns if not (pd.api.types.is_numeric_dtype(X[c]) or X[c].dtype == "category")]
    X = X.drop(columns=text)
    X["hour"] = tx["ts"].dt.hour
    X["cents"] = (tx["TransactionAmt"] * 100 % 100).round()
    return X


def main():
    tx = load()
    cc = pd.read_csv(config.DATASET / "closed_cases_history.csv", dtype=str).fillna("")
    cc["opened_at"] = pd.to_datetime(cc["opened_at"])
    lab = {}
    for c in cc.itertuples():
        for t in c.txn_ids.split("|"):
            lab[t] = (int(c.outcome == "confirmed_fraud"), c.opened_at)
    y = tx["TransactionID"].map(lambda t: lab.get(t, (np.nan,))[0])
    hist = tx["ts"] < "2016-11-01"
    rng = np.random.default_rng(0)
    bg = hist & y.isna() & (rng.random(len(tx)) < 0.15)
    y = y.where(~bg, 0)

    X = features(tx)
    cat_mask = [c in CAT for c in X.columns]
    labelled = y.notna()
    early = tx["ts"] < "2016-09-01"
    params = dict(max_iter=400, learning_rate=0.06, max_leaf_nodes=48, categorical_features=cat_mask,
                  l2_regularization=1.0, random_state=0)

    tr, te = labelled & early, labelled & ~early & hist
    m = HistGradientBoostingClassifier(**params).fit(X[tr], y[tr])
    p = m.predict_proba(X[te])[:, 1]
    in_case = te & tx["TransactionID"].isin(lab)
    report = {"train_rows": int(tr.sum()), "test_rows": int(te.sum()),
              "auc_all_test": round(roc_auc_score(y[te], p), 4),
              "auc_case_txns_confirmed_vs_cleared": round(roc_auc_score(y[in_case], p[in_case[te].values]), 4)}
    # risk score alone on the same case txns, for comparison
    report["auc_risk_score_case_txns"] = round(roc_auc_score(y[in_case], tx.loc[in_case, "risk_score"]), 4)
    print(report)

    final = HistGradientBoostingClassifier(**params).fit(X[labelled], y[labelled])
    tx["model_score"] = final.predict_proba(X)[:, 1]
    # labelled rows get out-of-fold scores (grouped by customer) so thresholds tuned on them are honest
    idx = np.flatnonzero(labelled.values)
    for fit_i, pred_i in GroupKFold(5).split(idx, groups=tx["customer_id"].values[idx]):
        m = HistGradientBoostingClassifier(**params).fit(X.iloc[idx[fit_i]], y.iloc[idx[fit_i]])
        tx.iloc[idx[pred_i], tx.columns.get_loc("model_score")] = m.predict_proba(X.iloc[idx[pred_i]])[:, 1]
    tx[["TransactionID", "model_score"]].to_parquet(config.PREP / "txn_scores.parquet", index=False)
    (config.PREP / "model_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
