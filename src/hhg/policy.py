"""Deterministic Fraud Policy engine (README "Fraud Policy" §0-§7). Pure functions over the
Findings dict defined in SPEC.md. Every reason cites the rule(s) it comes from."""

# §1 action identifiers, listed in the order they happen (§1: "order them by what happens first"):
# real-time controls, customer contact, card blocks, monitoring, record-keeping, hand-off, closure.
ORDER = [
    "DECLINE_TRANSACTION", "STEP_UP_AUTH", "VERIFY_WITH_CUSTOMER", "BLOCK_CARD", "BLOCK_ALL_CARDS",
    "MONITOR_CARD", "CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER",
    "ESCALATE_TO_ANALYST", "GENERATE_REPORT", "ALLOW_TRANSACTION", "CLOSE_NO_FRAUD",
]
ACTIONS = set(ORDER)
ROUTES = {"auto", "L1", "L2"}

# evidence type -> the action that requests it (§5), cheapest first
EVIDENCE = {"analyst_info": "ESCALATE_TO_ANALYST", "step_up_auth": "STEP_UP_AUTH",
            "customer_validation": "VERIFY_WITH_CUSTOMER"}
RESPONSES = {"analyst_info": ["fraud", "legitimate"], "step_up_auth": ["pass", "fail"],
             "customer_validation": ["deny", "confirm", "no_reply"]}


def route(action, exposure_usd):
    """§2 approval routing."""
    if action == "DECLINE_TRANSACTION":
        return "L1"
    if action == "BLOCK_CARD":
        return "L1" if exposure_usd <= 2500 else "L2"
    if action in ("BLOCK_ALL_CARDS", "FILE_REPORT"):
        return "L2"
    return "auto"


def _settled_fraud(f):
    # R1 lists STEP_UP_AUTH as a verification; a failed step-up is treated like a denial (§6 "a
    # verification response settles the question").
    return f.get("customer_response") == "deny" or f.get("step_up_result") == "fail"


def _settled_legit(f):
    # A passed step-up proves nothing when credentials are compromised (account takeover, R10).
    return f.get("customer_response") == "confirm" or (
        f.get("step_up_result") == "pass" and not f.get("credentials_compromised"))


def _strong(f):
    # §3a "confirmed or strongly suspected": a denial/failed step-up, or a fraud verdict at the §6
    # stopping threshold (0.85). Below that we verify first, as in the README example (0.72 -> verify).
    return _settled_fraud(f) or (f["verdict"] == "fraud" and f["fraud_probability"] >= 0.85)


def _r9(f):
    # R9: undocumented pattern with coordinated/repeated abuse across customers or cards.
    return f["pattern"] == "undocumented" and f["verdict"] != "legitimate" and bool(
        f.get("shared_origin") or f.get("connects_to_other_fraud"))


def _sar_grounds(f):
    """§3a report conditions that hold (only meaningful once fraud is strongly suspected)."""
    e, grounds = f["exposure_usd"], []
    if e > 1000:
        grounds.append(f"exposure ${e:,.2f} exceeds $1,000")
    if f.get("shared_origin"):
        s = f["shared_origin"]
        grounds.append(f"shared {s['kind']} {s['id']} links cards {', '.join(s['card_ids'])}")
    if f.get("connects_to_other_fraud"):
        grounds.append("activity connects to another card's or customer's fraud")
    if _r9(f):
        grounds.append("coordinated undocumented pattern (R9)")
    return grounds


def needs_case(f):
    """§3a: open a case when p >= 0.30, when evidence is requested, or when a customer disputes."""
    return (f["fraud_probability"] >= 0.30 or f["trigger_type"] == "customer_report"
            or f.get("customer_response") is not None or f.get("step_up_result") is not None)


def _case_reason(f):
    if f["trigger_type"] == "customer_report":
        return "§3a: customer disputed a charge"
    if f.get("customer_response") is not None or f.get("step_up_result") is not None:
        return "§3a: evidence was requested"
    return f"§3a: fraud probability {f['fraud_probability']:.2f} reaches 0.30"


def needs_sar(f, actions):
    """§3a: (file?, reason). Agrees with FILE_REPORT in `actions` by construction."""
    names = [a["action"] for a in actions]
    if "FILE_REPORT" in names:
        return True, next(a["reason"] for a in actions if a["action"] == "FILE_REPORT")
    if "CLOSE_NO_FRAUD" in names:
        return False, "§3a: no report; activity closed as legitimate (R3)"
    if not (_strong(f) or _r9(f)):
        return False, "§3a: no report; fraud is not confirmed or strongly suspected"
    return False, "§3a: no report; exposure is under $1,000, no shared element or other fraud, pattern not coordinated"


def decide(f):
    """Ordered [{"action","route","reason"}] for the findings as they stand now."""
    p, e, v = f["fraud_probability"], f["exposure_usd"], f["verdict"]
    resp = f.get("customer_response")
    acts = {}

    def add(action, reason):
        acts.setdefault(action, [])
        if reason not in acts[action]:
            acts[action].append(reason)

    def block(reason):
        if f.get("customer_cards_confirmed_fraud", 0) >= 2 or f.get("credentials_compromised"):
            why = ("credentials confirmed compromised" if f.get("credentials_compromised")
                   else f"{f['customer_cards_confirmed_fraud']} of the customer's cards show confirmed fraud")
            add("BLOCK_ALL_CARDS", f"R10: {why}; {reason}")
        else:
            side = "under" if e <= 2500 else "over"
            add("BLOCK_CARD", f"{reason}; exposure ${e:,.2f} is {side} $2,500 (§2)")

    if _settled_legit(f):
        who = "customer confirmed the transaction" if resp == "confirm" else "step-up authentication passed"
        add("CLOSE_NO_FRAUD", f"R3: {who}; confirmation noted in the case file")
        if f.get("recurring_match"):
            add("WARN_CUSTOMER", "R7: charge matches the customer's own recurring pattern; send a recurring-charge reminder")
    else:
        r1 = f["single_signal"] and p < 0.70
        if _settled_fraud(f):
            who = "customer denied the transaction" if resp == "deny" else "step-up authentication failed"
            block(f"R2: {who}")
            add("CREATE_CASE", f"R2: {who}")
        elif resp == "no_reply":
            add("MONITOR_CARD", "R4: no reply within 24 hours; raise monitoring for 72 hours")
            add("DECLINE_TRANSACTION", "R4: no reply within 24 hours; decline pending authorizations")
            if e > 500:
                add("ESCALATE_TO_ANALYST", f"R4: no reply and exposure ${e:,.2f} exceeds $500")
        elif f.get("recurring_match"):
            add("CREATE_CASE", "R7: disputed charge matches the customer's recurring pattern")
            add("VERIFY_WITH_CUSTOMER", "R7: confirm the recurring charge with the customer; do not block")
            add("WARN_CUSTOMER", "R7: send a recurring-charge reminder")
        elif v == "legitimate":
            add("CLOSE_NO_FRAUD", f"§0/§6: evidence supports a legitimate verdict (probability {p:.2f})")
        elif f.get("card_testing"):
            add("DECLINE_TRANSACTION", "R5: three or more small online authorizations within an hour, then a larger purchase")
            add("STEP_UP_AUTH", "R5: card-testing sequence observed")
            if f.get("cleared_purchase_over_100"):
                if r1:
                    add("STEP_UP_AUTH", f"R1: single signal at probability {p:.2f}; verify before blocking")
                else:
                    block("R5: a purchase over $100 already cleared in the testing sequence")
        elif r1:
            add("VERIFY_WITH_CUSTOMER", f"R1: single signal at probability {p:.2f} < 0.70; verify before any block")
        elif v == "fraud" and p >= 0.85:
            block(f"R1 not triggered: {f['independent_evidence']} independent signals at probability {p:.2f}")
        else:
            if v == "fraud":
                add("DECLINE_TRANSACTION", f"§5/R1: fraud likely (probability {p:.2f}); hold the flagged authorization")
            # Below the §6 threshold a block is not yet defensible; confirm first (README §3b example).
            add("VERIFY_WITH_CUSTOMER", f"R1/§5: probability {p:.2f} is below 0.85; confirm with the customer before blocking")

        # Overlays that hold whatever the customer said (except a confirmation).
        s = f.get("shared_origin")
        if s and v != "legitimate":
            add("CREATE_CASE", f"R6: several cards show fraud from shared {s['kind']} {s['id']}")
            add("MONITOR_CONNECTED_CARDS", f"R6: monitor every card sharing {s['kind']} {s['id']}: {', '.join(s['card_ids'])}")
        if _r9(f):
            add("CREATE_CASE", "R9: undocumented pattern with coordinated abuse across cards/customers")
            add("ESCALATE_TO_ANALYST", "R9: undocumented coordinated pattern needs analyst review")
        grounds = _sar_grounds(f)
        if grounds and (_strong(f) or _r9(f)):
            rule = "R9" if _r9(f) and not _strong(f) else ("R2" if _settled_fraud(f) else "§3a")
            if s:
                rule += "/R6"
            add("FILE_REPORT", f"{rule}: fraud confirmed or strongly suspected and " + "; ".join(grounds))
        uncertain = v == "uncertain" and not _settled_fraud(f)
        if uncertain and e > 500:
            add("ESCALATE_TO_ANALYST", f"R8: verdict uncertain and exposure ${e:,.2f} exceeds $500")
        if f.get("evidence_conflicts"):
            add("ESCALATE_TO_ANALYST", "R8: prosecution and defence evidence conflict")

    if needs_case(f):
        add("CREATE_CASE", _case_reason(f))
    elif "VERIFY_WITH_CUSTOMER" in acts or "STEP_UP_AUTH" in acts:
        add("CREATE_CASE", "§3a: evidence requested")

    return [{"action": a, "route": route(a, e), "reason": "; ".join(acts[a])} for a in ORDER if a in acts]


def _names(f):
    return {a["action"] for a in decide(f)}


def _simulate(f, etype, response):
    if etype == "customer_validation":
        return {**f, "customer_response": response}
    if etype == "step_up_auth":
        return {**f, "step_up_result": response}
    # analyst_info: the analyst resolves the conflict one way; probability moves to the §6 threshold.
    return {**f, "evidence_conflicts": False, "verdict": response,
            "fraud_probability": 0.85 if response == "fraud" else 0.15}


def apply_response(f, etype, resp):
    """Findings after a response to an evidence request arrives (the agent's evidence model; the UI's
    what-if replays it). A reply settles the question, so probability and verdict move with it."""
    if resp == "no_reply":  # R4: silence is not evidence either way
        return {**f, "customer_response": "no_reply"}
    f, fraud = dict(f), resp in ("deny", "fail", "fraud")
    p = f["fraud_probability"]
    if etype == "customer_validation":
        f["customer_response"] = resp
    elif etype == "step_up_auth":
        f["step_up_result"] = resp
    if etype == "analyst_info":  # same modelling of an analyst answer as _simulate
        f.update(evidence_conflicts=False, fraud_probability=0.85 if fraud else 0.15)
    else:
        f["fraud_probability"] = max(p, 0.9) if fraud else min(p, 0.1)
    f["verdict"] = "fraud" if fraud else "legitimate"
    f["independent_evidence"] += 1
    if not fraud:
        f.update(pattern="none", exposure_usd=0.0, shared_origin=None, connects_to_other_fraud=False)
    return f


def evidence_gate(f):
    """Decision-flip test. Only evidence the current actions actually request is considered
    (§3b "request more evidence if the policy calls for it"): customer_validation if
    VERIFY_WITH_CUSTOMER is recommended, step_up_auth if STEP_UP_AUTH is, analyst_info only when the
    evidence conflicts (R8). For customer_report triggers customer_validation means asking the
    disputing customer to confirm details: a deny upholds the dispute, a confirm withdraws it.
    Returns the cheapest request whose possible responses change the action set, else None."""
    now = _names(f)
    for etype, action in EVIDENCE.items():
        if etype == "analyst_info":
            if not f.get("evidence_conflicts"):
                continue
        elif action not in now:
            continue
        if etype == "customer_validation" and f.get("customer_response") is not None:
            continue
        if etype == "step_up_auth" and f.get("step_up_result") is not None:
            continue
        outcomes = {r: [a["action"] for a in decide(_simulate(f, etype, r))] for r in RESPONSES[etype]}
        if any(set(o) != now for o in outcomes.values()):
            detail = "; ".join(r + " -> " + ", ".join(o) for r, o in outcomes.items())
            why = f"§3b/§5: {action} is recommended and the {etype} response changes the actions ({detail})"
            return {"type": etype, "why": why, "outcomes": outcomes}
    return None


def should_stop(f):
    """§6 stopping rules: (stop?, reason)."""
    p, n = f["fraud_probability"], f["independent_evidence"]
    if _settled_fraud(f) or _settled_legit(f):
        return True, "§6: the verification response settles the question"
    if (p >= 0.85 or p <= 0.15) and n >= 2:
        return True, f"§6: probability {p:.2f} is decisive and rests on {n} independent pieces of evidence"
    gate = evidence_gate(f)
    if gate is None:
        return True, "§6: further steps are unlikely to change the decision; no response to any warranted evidence request changes the actions"
    return False, gate["why"]


def status_for(f, final_actions):
    """Case status once the agent stops (Answer Format Part 1)."""
    names = {a["action"] for a in final_actions}
    if "CLOSE_NO_FRAUD" in names:
        return "closed_legitimate"
    if "ESCALATE_TO_ANALYST" in names:
        return "escalated"
    if names & {"BLOCK_CARD", "BLOCK_ALL_CARDS"}:
        return "closed_fraud"
    return "open"
