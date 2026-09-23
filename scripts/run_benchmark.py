"""Run the agent on the 20 benchmark cases, in opened_at order (earlier AgentCases are memory for later ones).

    PYTHONPATH=src python scripts/run_benchmark.py [--only HHG-014[,HHG-003]] [--no-write-graph]

Writes cases/<case_id>.json and cases/traces/<case_id>.json, then validates cases/.
"""
import argparse
import csv
import json
import sys
import traceback

from hhg import config
from hhg.agent import investigate
from hhg.validate import validate_answer

CASES = config.ROOT / "cases"


def load_amounts():
    """txn id -> amount from data_prep/txn_*.csv (the graph load files), or None if absent."""
    files = sorted(config.PREP.glob("txn_*.csv"))
    if not files:
        return None
    amounts = {}
    for p in files:
        with open(p, newline="", encoding="utf-8") as fh:
            amounts.update((r["id"], float(r["amount"])) for r in csv.DictReader(fh))
    return amounts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--no-write-graph", action="store_true")
    args = ap.parse_args(argv)

    with open(config.DATASET / "case_pack.csv", newline="", encoding="utf-8") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: r["opened_at"])
    if args.only:
        only = set(args.only.split(","))
        rows = [r for r in rows if r["case_id"] in only]
    (CASES / "traces").mkdir(parents=True, exist_ok=True)

    failed = []
    for r in rows:
        print(f"--- {r['case_id']} ({r['opened_at']}, {r['trigger_type']})", flush=True)
        try:
            answer, trace = investigate(r, write_graph=not args.no_write_graph)
        except Exception:
            traceback.print_exc()
            failed.append(r["case_id"])
            continue
        (CASES / f"{r['case_id']}.json").write_text(json.dumps(answer, indent=2, ensure_ascii=False), encoding="utf-8")
        (CASES / "traces" / f"{r['case_id']}.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False),
                                                               encoding="utf-8")

    amounts = load_amounts()
    head = f"{'case':8} {'ok':4} {'status':17} {'verdict':10} {'p':>5} {'pattern':27} {'txns':>4} {'exposure':>10} " \
           f"{'sar':3} {'req':3} {'calls':>5} {'tok':>6} {'s':>6}  final actions"
    print("\n" + head + "\n" + "-" * len(head))
    bad = 0
    for r in rows:
        p = CASES / f"{r['case_id']}.json"
        if r["case_id"] in failed or not p.exists():
            print(f"{r['case_id']:8} FAIL (no answer)")
            bad += 1
            continue
        a = json.loads(p.read_text(encoding="utf-8"))
        errs, _ = validate_answer(a, amounts)
        bad += bool(errs)
        c = a["case"]
        print(f"{a['case_id']:8} {'OK' if not errs else 'BAD':4} {c['status']:17} {c['verdict']:10} "
              f"{c['fraud_probability']:5.2f} {c['pattern']:27} {len(c['affected_txn_ids']):4} {c['exposure_usd']:10.2f} "
              f"{'Y' if a['sar']['file'] else '-':3} {len(a['evidence_requests']):3} {a['tool_calls']:5} {a['tokens']:6} "
              f"{a['latency_s']:6.1f}  {', '.join(x['action'] for x in a['next_best_actions']['final'])}")
        for e in errs:
            print(f"         ERROR {e}")
    print(f"\n{len(rows) - bad}/{len(rows)} valid" + ("" if amounts else " (exposure not checked: no data_prep/txn_*.csv)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
