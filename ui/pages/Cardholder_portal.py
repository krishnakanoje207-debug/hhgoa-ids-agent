"""Cardholder portal: the bank customer's side of an investigation.

A cardholder answers the fraud team's "did you make this purchase?" (customer_validation), which the analyst
console then uses, and can report a transaction they don't recognise, which opens a customer_report case
through hhg.intake. Customers see plain-language next steps only: no probabilities, internal routes, or
anything about a suspicious activity report (a SAR must never be disclosed to its subject).
"""
import json
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hhg import policy, replies  # noqa: E402

st.set_page_config(page_title="Cardholder portal", layout="centered")
AMOUNT = re.compile(r"\$[\d,]+\.\d\d")  # the purchase amount in the trigger text

# customer-facing wording; internal actions (FILE_REPORT, ESCALATE_TO_ANALYST, ...) are not shown
SAY = {
    "BLOCK_CARD": "Your card will be blocked and a new one sent to you.",
    "BLOCK_ALL_CARDS": "All your cards will be blocked and replaced.",
    "DECLINE_TRANSACTION": "Pending payments on your card will be declined.",
    "STEP_UP_AUTH": "We may ask you for a one-time passcode on your next purchase.",
    "VERIFY_WITH_CUSTOMER": "We need you to confirm a purchase (see above).",
    "MONITOR_CARD": "We are keeping a closer watch on your card for the next 72 hours.",
    "WARN_CUSTOMER": "We'll send you a reminder about your recurring charges.",
    "CLOSE_NO_FRAUD": "No fraud found: your card stays active and the case is closed.",
    "CREATE_CASE": "We have opened a case to look into this.",
}


def load(directory):
    out = {}
    for p in sorted(directory.glob("*.json")):
        tp = directory / "traces" / p.name
        if tp.exists():
            out[p.stem] = (json.loads(p.read_text(encoding="utf-8")), json.loads(tp.read_text(encoding="utf-8")))
    return out


def next_steps(case_id, answer, trace):
    if trace.get("findings"):
        f, pending = replies.replay(case_id, trace, assume_customer=False)
        actions = policy.decide(f)
    else:
        pending, actions = None, answer["next_best_actions"]["final"]
    lines = [SAY[a["action"]] + (" (a member of our fraud team approves this first)" if a["route"] != "auto" else "")
             for a in actions if a["action"] in SAY and not (pending and a["action"] == "VERIFY_WITH_CUSTOMER")]
    return lines, pending


st.title("Cardholder portal")
st.caption("Demo sign-in: a real portal would authenticate the cardholder. Try C04570 (case HHG-017).")
customer = st.text_input("Customer ID", value="C04570").strip()
if not customer:
    st.stop()
if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))

cases = {**load(ROOT / "cases"), **load(ROOT / "cases_new")}
mine = {cid: (a, t) for cid, (a, t) in cases.items() if t["trigger"]["customer_id"] == customer}

st.subheader("Questions from our fraud team")
asked = 0
for cid, (a, t) in sorted(mine.items()):
    if not t.get("findings"):
        continue
    _, pending = replies.replay(cid, t, assume_customer=False)
    answered = replies.latest(cid)
    if pending != "customer_validation" and not answered:
        continue
    asked += 1
    trig = t["trigger"]
    amount = AMOUNT.search(trig["trigger_text"])
    with st.container(border=True):
        st.markdown(f"**Did you make this purchase?** {amount.group(0).replace('$', '\\$') + ' ' if amount else ''}"
                    f"on card `{trig['card_id']}`, transaction `{trig['flagged_txn_id']}` "
                    f"(case {cid}, opened {trig['opened_at'][:16]}).")
        if answered:
            st.success("You answered: " + ("yes, it was me." if answered["response"] == "confirm"
                                           else "no, it wasn't me."))
        else:
            c1, c2 = st.columns(2)
            if c1.button("Yes, it was me", key=f"yes-{cid}"):
                replies.record(cid, customer, "confirm")
                st.rerun()
            if c2.button("No, it wasn't me", key=f"no-{cid}", type="primary"):
                replies.record(cid, customer, "deny")
                st.rerun()
if not asked:
    st.caption("Nothing to confirm right now.")

st.subheader("Your cases")
if not mine:
    st.caption("No open or recent cases.")
for cid, (a, t) in sorted(mine.items()):
    lines, pending = next_steps(cid, a, t)
    with st.expander(f"{cid} · transaction {t['trigger']['flagged_txn_id']}"):
        if pending and pending != "customer_validation":
            st.write("Our fraud team is reviewing this case.")
        for line in lines:
            st.write("• " + line)

st.subheader("Report a transaction you don't recognise")
if st.button("Show my recent transactions"):
    try:
        from hhg import intake  # needs .env and a reachable TigerGraph workspace
        with st.spinner("Loading your transactions…"):
            st.session_state[f"txns-{customer}"] = intake.customer_txns(customer)[:50]
    except Exception as e:
        st.error(f"Could not load transactions right now ({type(e).__name__}). Please try again in a minute.")
txns = st.session_state.get(f"txns-{customer}")
if txns:
    pick = st.selectbox("Transaction", [r["id"] for r in txns], format_func=lambda i: next(
        f"{r['ts'][:16]} · ${r['amount']:,.2f} · {r['channel']} · card {r['card']}" for r in txns if r["id"] == i))
    words = st.text_input("What happened? (optional)", placeholder="I never made this purchase.")
    if st.button("Report this transaction", type="primary"):
        from hhg import intake
        with st.spinner("Checking your card… this takes about 30 seconds."):
            try:
                answer, trace, _ = intake.open_case(pick, "customer_report", words.strip())
            except Exception as e:
                st.error(f"We couldn't open a case right now ({type(e).__name__}). Please try again in a minute.")
                st.stop()
        _, pending = replies.replay(answer["case_id"], trace, assume_customer=False)
        st.session_state["flash"] = f"Thank you. Case {answer['case_id']} is open" + (
            ". One more step: please confirm the purchase under *Questions from our fraud team*."
            if pending == "customer_validation" else ". See *Your cases* for what happens next.")
        st.rerun()
