"""Answer-file validator (README "Answer Format").

    PYTHONPATH=src python -m hhg.validate cases/ [--txn-amounts transactions.csv]

--txn-amounts takes any CSV with TransactionID and TransactionAmt columns (e.g. dataset
transactions.csv) and enables the exposure == sum(affected amounts) check (§4)."""
import csv
import datetime
import json
import re
import sys
from pathlib import Path

from hhg.policy import ACTIONS, ROUTES, route

NUM = (int, float)
STATUS = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VERDICT = {"fraud", "legitimate", "uncertain"}
PATTERN = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use",
           "account_takeover", "undocumented", "none"}
SOURCE = {"graph", "document", "customer", "external"}
REQUEST = {"customer_validation", "step_up_auth", "analyst_info"}

TOP = {"case_id": str, "case": dict, "evidence_requests": list, "next_best_actions": dict, "sar": dict,
       "stop_reason": str, "tool_calls": int, "tokens": int, "latency_s": NUM}
CASE = {"status": str, "verdict": str, "fraud_probability": NUM, "pattern": str, "pattern_description": str,
        "affected_txn_ids": list, "first_suspicious_txn_id": str, "connected_card_ids": list,
        "connected_device_profiles": list, "exposure_usd": NUM, "evidence": list, "similar_prior_cases": list,
        "summary": str, "written_to_graph": bool, "graph_case_id": str}
EVIDENCE = {"claim": str, "source": str, "ref": str, "entity_ids": list}
EREQ = {"type": str, "asked_after_step": int, "assumed_response": str}
SAR = {"file": bool, "reason": str, "narrative": str, "subjects": list, "total_amount_usd": NUM,
       "activity_dates": list}
NBA = {"initial": list, "final": list, "what_changed": str}
ACTION = {"action": str, "route": str, "reason": str}


def _fields(obj, spec, where, errs):
    """Presence + type check. Returns False if obj is unusable."""
    if not isinstance(obj, dict):
        errs.append(f"{where}: expected object")
        return False
    ok = True
    for k, t in spec.items():
        if k not in obj:
            errs.append(f"{where}.{k}: missing")
            ok = False
        elif not isinstance(obj[k], t) or (t is not bool and isinstance(obj[k], bool)):
            errs.append(f"{where}.{k}: wrong type {type(obj[k]).__name__}")
            ok = False
    return ok


def _sentences(text):
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$\"(])", text.strip()) if s])


def _date(s):
    try:
        datetime.date.fromisoformat(s)
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None
    except (TypeError, ValueError):
        return False


def validate_answer(ans, amounts=None, known_ids=None):
    """Return (errors, warnings) for one answer dict. `amounts`: txn id -> amount; `known_ids`: all dataset IDs."""
    errs, warns = [], []
    if not isinstance(ans, dict):
        return ["answer is not a JSON object"], warns
    _fields(ans, TOP, "", errs)
    c, sar, nba = ans.get("case"), ans.get("sar"), ans.get("next_best_actions")
    ok_case = isinstance(c, dict) and _fields(c, CASE, "case", errs)
    ok_sar = isinstance(sar, dict) and _fields(sar, SAR, "sar", errs)
    ok_nba = isinstance(nba, dict) and _fields(nba, NBA, "next_best_actions", errs)
    requests = ans.get("evidence_requests") if isinstance(ans.get("evidence_requests"), list) else []

    for i, r in enumerate(requests):
        if _fields(r, EREQ, f"evidence_requests[{i}]", errs) and r["type"] not in REQUEST:
            errs.append(f"evidence_requests[{i}].type: invalid {r['type']!r}")

    if ok_case:
        if c["status"] not in STATUS:
            errs.append(f"case.status: invalid {c['status']!r}")
        if c["verdict"] not in VERDICT:
            errs.append(f"case.verdict: invalid {c['verdict']!r}")
        if c["pattern"] not in PATTERN:
            errs.append(f"case.pattern: invalid {c['pattern']!r}")
        if not 0 <= c["fraud_probability"] <= 1:
            errs.append("case.fraud_probability: outside [0, 1]")
        if (c["pattern"] == "undocumented") != bool(c["pattern_description"].strip()):
            errs.append("case.pattern_description: required iff pattern is undocumented, else \"\"")
        for cc in c["similar_prior_cases"]:
            if not re.fullmatch(r"CC-\d{4}", str(cc)):
                errs.append(f"case.similar_prior_cases: bad id {cc!r}")
        for i, ev in enumerate(c["evidence"]):
            if _fields(ev, EVIDENCE, f"case.evidence[{i}]", errs) and ev["source"] not in SOURCE:
                errs.append(f"case.evidence[{i}].source: invalid {ev['source']!r}")
        if c["verdict"] == "legitimate" and (c["affected_txn_ids"] or c["exposure_usd"] != 0):
            errs.append("legitimate verdict: affected_txn_ids must be empty and exposure_usd 0")
        if amounts is not None:
            missing = [t for t in c["affected_txn_ids"] if t not in amounts]
            if missing:
                errs.append(f"case.affected_txn_ids: no amount for {missing}")
            else:
                total = sum(abs(amounts[t]) for t in c["affected_txn_ids"])
                if abs(total - c["exposure_usd"]) > 0.01:
                    errs.append(f"case.exposure_usd: {c['exposure_usd']} != sum of affected amounts {total:.2f}")

    if ok_nba:
        exposure = c["exposure_usd"] if ok_case else None
        for part in ("initial", "final"):
            for i, a in enumerate(nba[part]):
                where = f"next_best_actions.{part}[{i}]"
                if not _fields(a, ACTION, where, errs):
                    continue
                if a["action"] not in ACTIONS:
                    errs.append(f"{where}.action: unknown {a['action']!r}")
                    continue
                if a["route"] not in ROUTES:
                    errs.append(f"{where}.route: invalid {a['route']!r}")
                elif exposure is not None and a["route"] != route(a["action"], exposure):
                    errs.append(f"{where}: {a['action']} route {a['route']} != {route(a['action'], exposure)} (§2)")
                # §7 says cite the rule; a warning only, because the README's own example has one
                # reason ("Same device profile also used on C00877-K1") without a rule number.
                if not re.search(r"R\d+|§", a["reason"]):
                    warns.append(f"{where}.reason: cites no rule (R-number or §)")
                if a["action"] == "BLOCK_ALL_CARDS" and "R10" not in a["reason"]:
                    errs.append(f"{where}: BLOCK_ALL_CARDS without citing R10")
        if not requests and (nba["final"] != nba["initial"] or nba["what_changed"] != "nothing"):
            errs.append("no evidence_requests: final must equal initial and what_changed must be \"nothing\"")

    if ok_sar:
        if ok_nba:
            in_final = any(isinstance(a, dict) and a.get("action") == "FILE_REPORT" for a in nba["final"])
            if sar["file"] != in_final:
                errs.append("sar.file must agree with FILE_REPORT in next_best_actions.final")
        if ok_case and c["verdict"] == "legitimate" and sar["file"]:
            errs.append("legitimate verdict: sar.file must be false")
        if sar["file"]:
            n = _sentences(sar["narrative"])
            if not 6 <= n <= 12:
                errs.append(f"sar.narrative: {n} sentences, need 6-12")
            d = sar["activity_dates"]
            if len(d) != 2 or not all(_date(x) for x in d):
                errs.append("sar.activity_dates: need two YYYY-MM-DD strings")
        elif sar["narrative"] != "" or sar["subjects"] != [] or sar["total_amount_usd"] != 0 or sar["activity_dates"] != []:
            errs.append("sar.file false: narrative \"\", subjects [], total_amount_usd 0, activity_dates [] required")

    if known_ids is not None and ok_case:
        ids = list(c["affected_txn_ids"]) + list(c["connected_card_ids"]) + list(c["similar_prior_cases"])
        ids += [c["first_suspicious_txn_id"]] if c["first_suspicious_txn_id"] else []
        ids += [x for ev in c["evidence"] if isinstance(ev, dict) for x in ev.get("entity_ids", [])]
        ids += list(sar["subjects"]) if ok_sar else []
        unknown = sorted({str(x) for x in ids} - known_ids)
        if unknown:
            errs.append(f"unknown ids: {unknown}")
    return errs, warns


def _load_amounts(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["TransactionID"]: float(r["TransactionAmt"]) for r in csv.DictReader(fh)}


def main(argv):
    args = list(argv)
    amounts = None
    if "--txn-amounts" in args:
        i = args.index("--txn-amounts")
        amounts = _load_amounts(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        return 2
    target = Path(args[0])
    files = [target] if target.is_file() else sorted(target.glob("*.json"))
    if not files:
        print(f"no answer files in {target}")
        return 1
    bad = 0
    for p in files:
        try:
            errs, warns = validate_answer(json.loads(p.read_text(encoding="utf-8")), amounts)
        except json.JSONDecodeError as e:
            errs, warns = [f"invalid JSON: {e}"], []
        bad += bool(errs)
        print(f"{'FAIL' if errs else 'OK  '} {p.name}")
        for e in errs:
            print(f"  ERROR {e}")
        for w in warns:
            print(f"  WARN  {w}")
    print(f"{len(files) - bad}/{len(files)} files valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # messages contain "§"; Windows consoles default to cp1252
    sys.exit(main(sys.argv[1:]))
