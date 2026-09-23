"""Cardholder answers to the bank's "did you make this purchase?" (customer_validation, README §5), sent from
the cardholder portal. Appended to a JSONL log; the analyst console reads the latest one per case."""
import json
from datetime import datetime, timezone
from pathlib import Path

from hhg import policy

LOG = Path(__file__).resolve().parents[2] / "audit" / "replies.jsonl"
ANSWERS = ("confirm", "deny")  # "yes, it was me" / "no, it wasn't me"


def record(case_id, customer_id, response, log=LOG):
    if response not in ANSWERS:
        raise ValueError(f"response must be one of {ANSWERS}")
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "case_id": case_id,
             "customer_id": customer_id, "type": "customer_validation", "response": response}
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def latest(case_id, log=LOG):
    """The case's most recent reply, or None."""
    if not log.exists():
        return None
    with open(log, encoding="utf-8") as fh:
        found = [e for e in map(json.loads, filter(str.strip, fh)) if e["case_id"] == case_id]
    return found[-1] if found else None


def replay(case_id, trace, log=LOG, assume_customer=True):
    """(findings, pending evidence type or None) after the replies known so far: the cardholder's own reply for
    customer_validation, otherwise the reply the agent assumed; stops at the first request still unanswered.
    assume_customer=False ignores the agent's assumed customer reply (the portal asks the real customer)."""
    f = trace["findings"]
    assumed = [(s["args"]["type"], s["args"].get("assumed_response"))
               for s in trace["steps"] if s["name"] == "Request more evidence"]
    real = latest(case_id, log)
    for i in range(len(policy.EVIDENCE)):
        gate = policy.evidence_gate(f)
        if gate is None:
            return f, None
        if gate["type"] == "customer_validation" and (real or not assume_customer):
            resp = real["response"] if real else None
        else:
            resp = assumed[i][1] if i < len(assumed) and assumed[i][0] == gate["type"] else None
        if resp is None:
            return f, gate["type"]
        f = policy.apply_response(f, gate["type"], resp)
    return f, None
