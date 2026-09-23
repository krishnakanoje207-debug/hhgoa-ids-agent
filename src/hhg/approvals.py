"""Human sign-off on L1/L2 actions (README Fraud Policy §2: "L1 and L2 actions are recommended with the
route stated and wait for a human"). Every decision is appended to a JSONL audit log; nothing is rewritten."""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parents[2] / "audit" / "approvals.jsonl"
ROLES = {"L1": "team lead", "L2": "fraud manager"}
# §2: L1 needs a team lead, L2 a fraud manager. A fraud manager outranks a team lead, so may also sign L1.
SIGNS = {"L1": {"L1"}, "L2": {"L1", "L2"}}
DECISIONS = ("approved", "rejected")


def can_sign(role, route):
    return route in SIGNS.get(role, set())


def record(case_id, action, route, decision, role, analyst, note="", responses=(), log=LOG):
    """Append one decision. `responses` are the evidence replies the signed recommendation rests on."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not can_sign(role, route):
        raise PermissionError(f"a {ROLES.get(role, role)} cannot sign a {route} action (§2)")
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "case_id": case_id,
             "action": action, "route": route, "decision": decision, "role": role, "analyst": analyst,
             "note": note, "responses": [list(r) for r in responses]}
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history(case_id, log=LOG):
    """This case's decisions, oldest first."""
    if not log.exists():
        return []
    with open(log, encoding="utf-8") as fh:
        return [e for e in map(json.loads, filter(str.strip, fh)) if e["case_id"] == case_id]
