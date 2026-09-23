"""Push data_prep/*.csv into FraudGraph through the loading jobs in gsql/load_jobs.gsql.

Usage: python scripts/load_graph.py [txn|device|cases|docs|emb ...]   (no args = all, in order)
"""
import sys

from hhg import config, tg

P = config.PREP


def post(job, var, path):
    pieces = tg.load_file(job, var, path)
    stats = [r.get("statistics", {}).get("parsingStatistics", {}).get("fileLevel", {}) for p in pieces for r in p.get("results", [])]
    valid = sum(s.get("validLine", 0) for s in stats)
    bad = sum(v for s in stats for k, v in s.items() if k != "validLine" and isinstance(v, int))
    print(job, path.name, f"{len(pieces)} piece(s), {valid} valid lines, {bad} rejected")


def main(steps):
    if "device" in steps:
        post("load_device", "f", P / "device.csv")
    if "txn" in steps:
        for f in sorted(P.glob("txn_*.csv")):
            post("load_txn", "f", f)
    if "cases" in steps:
        post("load_closed_cases", "cases", P / "closed_case.csv")
        post("load_closed_cases", "rel", P / "closed_case_rel.csv")
    if "docs" in steps:
        post("load_docs", "f", P / "docs.csv")
    if "emb" in steps:
        post("load_emb_doc", "f", P / "emb_doc.txt")
        post("load_emb_closed", "f", P / "emb_closed.txt")
    print(tg.gsql("USE GRAPH FraudGraph\nSELECT count() FROM Txn\nSELECT count() FROM Card\nSELECT count() FROM ClosedCase"))


if __name__ == "__main__":
    main(sys.argv[1:] or ["device", "txn", "cases", "docs", "emb"])
