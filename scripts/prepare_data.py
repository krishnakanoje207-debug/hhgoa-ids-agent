"""Slim the raw CSVs into load files for TigerGraph (data_prep/*.csv) and check the card-ID rule.

transactions.csv has no card_id: cards in the cases look like C01234-K1. We derive
card = (customer_id, card4 network, card6 type), numbered K1.. in a fixed order per customer,
and verify the rule against every txn listed in closed_cases_history.csv and case_pack.csv.
"""
import sys

import pandas as pd

from hhg import config

RAW_TX = config.ROOT / "_dl" / "transactions.csv"
OUT = config.PREP
OUT.mkdir(exist_ok=True)

TX_COLS = ["TransactionID", "TransactionAmt", "ProductCD", "card4", "card6", "addr1", "addr2", "dist1",
           "P_emaildomain", "R_emaildomain", "C1", "C13", "D1", "D15", *[f"M{i}" for i in range(1, 10)],
           "customer_id", "ts", "channel", "risk_score"]
ID_COLS = ["TransactionID", "id_15", "id_23", "id_30", "id_31", "id_33", "DeviceType", "DeviceInfo"]


def code(x):
    """addr codes come as floats ('299.0'); keep the README's spelling."""
    return "" if pd.isna(x) else f"{float(x):.1f}"


def main():
    tx = pd.read_csv(RAW_TX, usecols=TX_COLS, dtype={"TransactionID": str, "customer_id": str})
    ident = pd.read_csv(config.DATASET / "identity.csv", usecols=ID_COLS, dtype=str)
    tx = tx.merge(ident, on="TransactionID", how="left")
    print("transactions", len(tx), "with identity", tx["DeviceInfo"].notna().sum() + tx["id_30"].notna().sum())

    # card rule
    tx["card4"] = tx["card4"].fillna("")
    tx["card6"] = tx["card6"].fillna("")
    kinds = tx[["customer_id", "card4", "card6"]].drop_duplicates().sort_values(["customer_id", "card6", "card4"])
    kinds["k"] = kinds.groupby("customer_id").cumcount() + 1
    tx = tx.merge(kinds, on=["customer_id", "card4", "card6"])
    tx["card_id"] = tx["customer_id"] + "-K" + tx["k"].astype(str)
    check_card_rule(tx)

    # device profile = DeviceInfo | OS | browser | screen (README answer format)
    dev_parts = tx[["DeviceInfo", "id_30", "id_31", "id_33"]].fillna("")
    has_dev = (dev_parts != "").any(axis=1)
    tx["device_id"] = dev_parts.agg(" | ".join, axis=1).where(has_dev, "")
    tx["dev_status"] = tx["id_15"].fillna("")
    tx["proxy"] = tx["id_23"].fillna("")

    tx["m_flags"] = tx[[f"M{i}" for i in range(1, 10)]].fillna("").agg("|".join, axis=1)
    for c in ["dist1", "C1", "C13", "D1", "D15"]:  # -1 = missing, so it isn't confused with a real 0
        tx[c] = tx[c].fillna(-1)
    tx["addr1"] = tx["addr1"].map(code)
    tx["addr2"] = tx["addr2"].map(code)
    out = tx.rename(columns={"TransactionID": "id", "TransactionAmt": "amount", "ProductCD": "product",
                             "risk_score": "risk", "P_emaildomain": "p_email", "R_emaildomain": "r_email",
                             "C1": "c1", "C13": "c13", "D1": "d1", "D15": "d15", "card4": "network",
                             "card6": "card_type"})
    cols = ["id", "ts", "amount", "product", "channel", "risk", "addr1", "addr2", "dist1", "p_email", "r_email",
            "m_flags", "c1", "c13", "d1", "d15", "card_id", "customer_id", "network", "card_type",
            "device_id", "dev_status", "proxy", "model_score"]
    scores = pd.read_parquet(OUT / "txn_scores.parquet").rename(columns={"TransactionID": "id"})
    out = out.merge(scores, on="id", how="left")
    out = out[cols].sort_values("ts")
    # split for upload size limits
    for i, start in enumerate(range(0, len(out), 100_000)):
        out.iloc[start:start + 100_000].to_csv(OUT / f"txn_{i}.csv", index=False)

    devices = tx.loc[has_dev, ["device_id", "DeviceInfo", "id_30", "id_31", "id_33", "DeviceType"]] \
        .drop_duplicates("device_id").fillna("")
    devices.columns = ["id", "device_info", "os", "browser", "screen", "device_type"]
    devices.to_csv(OUT / "device.csv", index=False)

    prep_cases()
    print("written to", OUT)


def prep_cases():
    cc = pd.read_csv(config.DATASET / "closed_cases_history.csv", dtype=str).fillna("")
    cc[["case_id", "outcome", "pattern", "opened_at", "closed_at", "n_txns", "exposure_usd", "actions_taken",
        "report_filed", "analyst_notes"]].assign(report_filed=cc["report_filed"].eq("Yes").astype(int)) \
        .to_csv(OUT / "closed_case.csv", index=False)
    rel = []
    for c in cc.itertuples():
        rel += [(c.case_id, "INVOLVES", t) for t in c.txn_ids.split("|") if t]
        rel.append((c.case_id, "ON_CARD", c.card_id))
        rel += [(c.case_id, "CONNECTED_TO", k) for k in c.connected_card_ids.split("|") if k]
    pd.DataFrame(rel, columns=["case_id", "edge", "target"]).to_csv(OUT / "closed_case_rel.csv", index=False)


def check_card_rule(tx):
    by_txn = tx.set_index("TransactionID")["card_id"]
    cc = pd.read_csv(config.DATASET / "closed_cases_history.csv", dtype=str).fillna("")
    pairs = [(t, c.card_id) for c in cc.itertuples() for t in c.txn_ids.split("|")]
    cp = pd.read_csv(config.DATASET / "case_pack.csv", dtype=str)
    pairs += list(zip(cp.flagged_txn_id, cp.card_id))
    bad = [(t, want, by_txn.get(t)) for t, want in pairs if by_txn.get(t) != want]
    print(f"card rule: {len(pairs) - len(bad)}/{len(pairs)} case txns match")
    if bad:
        print("mismatches (txn, expected, derived):", bad[:15])
        sys.exit(1)


if __name__ == "__main__":
    prep_cases() if sys.argv[1:] == ["cases"] else main()
