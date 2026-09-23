# Demo video script — about 4¾ minutes

Screen: Streamlit analyst console (`streamlit run ui/app.py`) plus a terminal panel showing
live MCP tool calls (or the trace file's `steps` list scrolling, if calls aren't visibly
streamed). Narration lines are suggestions, not a transcript to read verbatim.

---

**Numbers to say on camera** (put them on screen too; the console's Overview shows them):
**99.3%** verdict accuracy when it decides, on **1,376** held-out closed cases · only **2 of
1,258** frauds called legitimate · **99.6%** of fraud calls right · pattern right **92.8%** ·
model AUC **0.886** vs the bank's **0.052** · **20/20** exam answers valid.

## 0:00–0:20 — Cold open

**Show:** Console overview screen, cases list, badges for status/verdict/pattern/route.

**Say:** "This is an agent that investigates fraud the way an analyst does — it opens a case,
argues both sides, and only asks for evidence that could actually change the answer. It runs on
TigerGraph: the graph, the vectors, and the agent's own memory, all in one place. Let's watch it
work a real case."

---

## 0:20–1:00 — Trigger and investigate: HHG-014

**Show:** Open case HHG-014. Header shows the analyst-request trigger text: "several cards this
month show purchases from the same unusual device profile... review transaction 3478561 on
card C13487-K1." Switch to the timeline tab; MCP tool calls appear one by one.

**Say:** "HHG-014 comes in as an analyst request, not a score — someone noticed cards touching
the same odd device. The agent opens a case and starts pulling the neighbourhood through
TigerGraph MCP: `card_history` for this card's own timeline, then `device_neighbors` for the
device profile itself." *(point at the tool-call log: `run_installed_query(device_neighbors,
device_id=SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080, ...)`)* "That single query is doing the ring detection — it returns every
card that touched this device profile in the window, and whether any of them already have a
case."

---

## 1:00–1:40 — The ring lights up in the graph

**Show:** Graph neighbourhood tab. The device vertex in the centre, cards fanning out, one or
two flagged `subject`/`suspicious`, `ClosedCase` nodes attached.

**Say:** "Here's the ring: one device profile — a Samsung SM-G935F behind Chrome Android and an
anonymous proxy — used as a brand-new device by 19 other cards this month, all behind the proxy.
Only 52 cards have ever used it, and 44 closed cases already touch those cards. The nearest past
investigations — confirmed undocumented fraud like CC-3035 — came back through `similar_cases`,
a vector search over past case embeddings: this is the GraphRAG memory retrieval, not a raw
table join."

---

## 1:40–2:20 — The courtroom argues, then calibrates

**Show:** Courtroom tab: prosecution claims (shared device, new-to-account, proxy, linked
closed cases) on one side, the defence on the other (the closed-case model scores the flagged
transaction only 0.39; no trip or new-phone signature). Probability meter at 0.90.

**Say:** "Before deciding anything, the agent tests the innocent explanations as hard as the
guilty one — is this just someone's new phone? Is it a trip? Here, the defence's best point is
the trained fraud model, whose score is stored right on the transaction vertex: it rates this
transaction only 0.39. But there's no phone-upgrade pattern and no travel signal, and one
transaction can't explain away a device ring — the calibrated probability lands at 0.90."

---

## 2:20–3:00 — The flip gate, evidence, and final actions

**Show:** Next-best-action tab: the evidence gate returns no decisive question (three
independent signals at probability 0.90), so initial and final actions are the same:
`BLOCK_CARD` / L1 (exposure $187.33), `CREATE_CASE` / auto, `FILE_REPORT` / L2,
`MONITOR_CONNECTED_CARDS` / auto, `ESCALATE_TO_ANALYST` / auto.

**Say:** "The policy engine — plain deterministic code, not the LLM — checks whether asking the
customer could actually change the outcome. Here it can't: no possible answer changes the action
set, so the agent doesn't ask. It goes straight to block the card, open a case, file a
suspicious activity report, put every card that shares this device under monitoring, and
escalate the undocumented pattern to an analyst — each with its required approval route, and
each reason citing the exact policy rule."

**Show:** SAR tab — the generated narrative.

**Say:** "And because this connects to another cardholder's compromise, policy calls for a
report. The narrative is LLM-written prose over the same evidence list the policy engine already
decided on — it explains the decision, it doesn't make it."

---

## 3:00–3:20 — Case written back to the graph

**Show:** Brief cut to the graph tab or a terminal line: `add_node(AgentCase, ...)`,
`add_edges(...)`.

**Say:** "Closing the case writes it back into TigerGraph as its own vertex, linked to the
transactions, the cards, the device, and the closed case it matched — so the *next*
investigation that touches this device finds this one instantly."

---

## 3:20–3:40 — A legitimate case, closed without blocking

**Show:** Switch to HHG-010 (risk-score trigger, bank score 0.90). Courtroom tab: the closed-case
model scores the transaction 0.01 and the device profile is a common one (36 other cards in 30
days). The evidence-gate flip table: `deny → BLOCK_CARD, CREATE_CASE, FILE_REPORT` vs.
`confirm → CREATE_CASE, CLOSE_NO_FRAUD`. Final actions: `CREATE_CASE`, `CLOSE_NO_FRAUD`, route
`auto`.

**Say:** "Not every alert is fraud — half of this exam isn't. Here the bank's score was 0.90, but
the model trained on the bank's own closed cases says 0.01 and nothing else corroborates it.
The customer's answer would flip the decision, so this time the agent asks; the assumed reply
is a confirmation, and it closes the case as legitimate instead of blocking a real customer's
card. That restraint is scored too."

*(Optional swap if time allows: HHG-001 — model score 0.79 on an in-person purchase in region
444, away from home region 433: the courtroom's defence shows 6 earlier transactions on the same
underlying account, none in any closed case, which caps the probability at 0.15. It still asks the
customer before closing `CLOSE_NO_FRAUD` / auto. "It blocks nothing it shouldn't, and it doesn't
clear anyone on a hunch.")*

---

## 3:40–4:05 — The reply arrives, a human signs

**Show:** HHG-017 (bank score 0.57 on a $100.09 online purchase; agent probability 0.60).
*Evidence & approval* tab: the `customer_validation` request is *awaiting reply*, actions
`VERIFY_WITH_CUSTOMER` and `CREATE_CASE`, status `open`. Click **deny**: actions become
`BLOCK_CARD` / L1 and `CREATE_CASE`, and the probability moves from 0.60 to 0.90. With the
sidebar set to *team lead (L1)*, click **Approve** on `BLOCK_CARD`. The audit log row appears.
(Optionally click **confirm** first to show it close as `CLOSE_NO_FRAUD`.)

**Say:** "This one really is balanced, so the agent didn't guess the customer's answer. It
asked, and the case stays open. When the reply comes in, the analyst enters it and the same
policy engine re-decides straight away. A denial means block the card. That's an L1 action, so
the agent can't do it alone: a team lead approves it, and the approval is logged with the
evidence it was based on."

---

## 4:05–4:20 — Sentinel catch

**Show:** `sentinel_cases/` folder or a console panel listing an out-of-benchmark find from
`near_threshold_scan` (the sub-$500 structuring pattern) or `device_ring_scan`.

**Say:** "Outside the 20 graded cases, the agent can also scan on its own initiative —
here it caught a structuring pattern: several purchases just under $500 within an hour on one
card, a pattern the bank's five documented types don't name. It writes its own
description and flags it for review."

---

## 4:20–4:40 — What's next, and close

**Show:** Overview screen, all 20 cases with status badges. Optionally, cut to the README's
*Future scope* table.

**Say:** "What we'd build next: real customer channels instead of simulated replies, a proper
login and a tamper-proof audit trail for approvals, community detection on the graph, and an
agent that learns from how cases actually end. Every analyst decision becomes a label that
sharpens the next investigation. Twenty cases, one graph, one policy. Graph in, decision
explained, memory out. Thanks for watching."

---

### Recording notes
- Pre-load the console with `cases/` and `cases/traces/` already populated from
  `run_benchmark.py` so no live latency (including Savanna auto-resume) is on camera.
- Optional customer clip: open **Cardholder portal** in the sidebar, sign in as `C04570`,
  click **No, it wasn't me** on HHG-017, then switch back to the console. HHG-017's reply is now
  preset to deny, with `BLOCK_CARD` waiting for a team lead. Clear `audit/` before recording.
- Optional new-case clip: **New case** in the sidebar, transaction `3450629`, *Risk-score alert*
  (about 20–40 s). The console jumps to the new case when it finishes.
- Optional live clip: click **Investigate live** on HHG-017 (about 30 s). The steps stream in
  as the agent queries TigerGraph, and the result is checked against the recorded answer. Wake
  Savanna first (run it once off camera). If it fails, fall back to the recorded case.
- Have HHG-014's trace file open in a second monitor/terminal to narrate tool calls precisely
  if the UI doesn't stream them live.
- Backup cases if a segment needs replacing: HHG-006 (sub-$500 structuring, 4 purchases in 30
  minutes, $1,906.07, `FILE_REPORT` / L2) and HHG-019 (rare-device shared origin: a device
  profile only 5 cards ever used, same email pair on C06224-K2 and C11309-K1 →
  `MONITOR_CONNECTED_CARDS`, `FILE_REPORT`).
- Keep the SAR narrative on screen long enough to be readable, even briefly — judges may pause
  the video there.
