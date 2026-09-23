# Demo video script — 4:55

One continuous screen recording of the analyst console and the cardholder portal
(`streamlit run ui/app.py`, browser at `http://localhost:8501`). Each segment gives what to
**click**, what the viewer **sees**, and what to **say**. About 2.4 spoken words per second fits
the timings. Appendix A explains every part of the screen, for questions or a longer cut.

**Numbers to say on camera, and to put on screen as captions:**

| | |
|---|---|
| Verdict accuracy when the agent decides | **99.3%** (1,376 held-out closed cases) |
| Fraud wrongly called legitimate | **2 of 1,258** |
| "Fraud" calls that were fraud | **99.6%** |
| Fraud pattern named correctly | **92.8%** |
| Our model vs the bank's risk score (AUC) | **0.886 vs 0.052** |
| Exam cases | **20 of 20** valid, all written to the graph |

---

## Before you record

- [ ] Delete `audit/` and `cases_new/` so the audit log and new-case list start empty.
- [ ] Start the console: `.venv\Scripts\streamlit.exe run ui\app.py`, browser at 100% zoom, window
      about 1600×900, dark or light theme (both render).
- [ ] Wake Savanna **off camera**: open any case and click **Investigate live** once. A
      "Failed to start workspace: 403" means the IP allowlist needs your current IP.
- [ ] Sidebar: **Signed in as** = *team lead (L1)*, **Analyst name** = your name.
- [ ] Have `sentinel_cases/SUMMARY.md` open in a second tab (GitHub or your editor).
- [ ] Rehearse once: the only live waits are segment 12 (about 20 s, speed it up in the edit)
      and any Investigate live click.

---

## 1. 0:00–0:20 — Hook: the numbers

**Click:** Sidebar → **Overview**.
**Sees:** The **Results** panel: five tiles reading 99.3%, 2 of 1,258, 99.6%, 92.8%, 0.886 vs 0.052.

**Say:** "This agent investigates card fraud on TigerGraph. On 1,376 of the bank's own closed
cases it never trained on, it's right 99.3 percent of the time when it decides. Only 2 of 1,258
frauds slipped through as legitimate. And the bank's own risk score? An AUC of 0.05. Worse than
guessing."

---

## 2. 0:20–0:40 — The case list and the sidebar

**Click:** Scroll to the **Overview — all cases** table; hover the columns. Then point at the sidebar.
**Sees:** 20 rows: trigger, verdict, pattern, probability, exposure, SAR, number of final
actions, status. Tiles under it: **10** fraud · **6** legitimate · **4** uncertain.

**Say:** "Twenty exam cases, all answered: 10 fraud, 6 legitimate, and 4 honestly uncertain. On
the left: every case, a **New case** form, who's signed in (team lead or fraud manager), and a
second page, the **cardholder portal**, which is the customer's side."

---

## 3. 0:40–1:00 — A case opens: HHG-014

**Click:** Sidebar → **HHG-014**.
**Sees:** Header with the analyst-request trigger ("several cards this month show purchases from
the same unusual device profile… transaction 3478561 on card C13487-K1"), badges
`escalated · fraud · undocumented · p = 0.90`, exposure **$187.33**, and the **Investigate live**
button.

**Say:** "HHG-014 isn't a score, it's an analyst's hunch: cards touching the same odd device.
The badges show where it landed: fraud, at 0.90, an undocumented pattern. **Investigate live**
re-runs the real agent on this trigger at any time. Let's see how it got here."

---

## 4. 1:00–1:20 — Timeline: the agent's steps

**Click:** Tab **Timeline**.
**Sees:** **18** tool calls · **7,897** tokens · **18.6 s**; 14 steps, each with its tool
(`tigergraph__run_installed_query`, `llm`, `tigergraph__add_node`) and a one-line result.

**Say:** "Every step is recorded. The agent reaches TigerGraph only through MCP, with an
allowlist that can't change the schema or delete anything. It reads the card, the customer and
the device. The LLM picks extra queries. The last step writes this case back into the graph."

---

## 5. 1:20–1:45 — Graph: the ring

**Click:** Tab **Graph**.
**Sees:** 45 nodes, 47 edges. The subject card in red, the device profile in the middle, other
cards fanning out, folder-shaped closed cases attached. The legend under the graph explains
colour (red subject · amber suspicious · green cleared · grey normal) and shape (entity type).

**Say:** "Here's what `device_neighbors` found. One Samsung profile behind Chrome and an
anonymous proxy, used as a brand-new device by 19 other cards this month. Only 52 cards have
ever used it, and 44 closed cases already touch those cards. That's a ring, and none of the bank's
five documented patterns covers it."

---

## 6. 1:45–2:05 — Courtroom: both sides

**Click:** Tab **Courtroom**.
**Sees:** **Prosecution** (ring 0.90, new device 0.60, anonymous proxy 0.60, episode 0.60) vs
**Defence** (the classifier scores the transaction only 0.39). The calibrated probability bar,
with markers at 0.15 / 0.30 / 0.70 / 0.85 and the case at 0.90.

**Say:** "Before deciding, it argues both sides, and tests the innocent explanations just as
hard: a trip, a new phone, a recurring charge. Here the defence is weak, and three independent
signals put it at 0.90. The markers are the policy's thresholds."

---

## 7. 2:05–2:15 — Evidence

**Click:** Tab **Evidence**.
**Sees:** Every claim with its source (graph, document, customer), the exact query it came from,
and the entity IDs. Chips: similar prior cases **CC-3035, CC-2971, CC-2649, CC-2985**.

**Say:** "Every claim cites its query and its IDs. These chips are the nearest past cases, from
vector search in TigerGraph."

---

## 8. 2:15–2:35 — Next best action

**Click:** Tab **Next best action**.
**Sees:** "No evidence gate recorded", initial and final actions identical:
`BLOCK_CARD` **L1** · `CREATE_CASE` auto · `FILE_REPORT` **L2** · `MONITOR_CONNECTED_CARDS` auto
· `ESCALATE_TO_ANALYST` auto, each with a reason citing a rule.

**Say:** "A policy engine decides, not the LLM. It asks for evidence only if a reply could
change the outcome. Here nothing could. Block the card, file a report, watch every card on that
device. Each action shows who approves it: auto, a team lead, or a fraud manager."

---

## 9. 2:35–2:50 — SAR and Summary

**Click:** Tab **SAR**, then **Summary**; open the **What the LLM saw** expander.
**Sees:** The narrative, subjects, total **$187.33**, activity dates **2016-11-15 – 2016-11-22**.
Then the case summary, the stop reason (*"§6: probability 0.90 is decisive and rests on 3
independent pieces of evidence"*), **Download raw answer JSON**, and the exact GraphRAG context.

**Say:** "The suspicious activity report is written from the same evidence. The LLM explains
the decision, it doesn't make it. Here is exactly what it was shown, and the stop reason cites
the rule that ended the investigation."

---

## 10. 2:50–3:15 — Restraint: HHG-010

**Click:** Sidebar → **HHG-010** → tab **Next best action**.
**Sees:** Bank risk score **0.90** on a **$1,000.03** online purchase. Evidence-gate table:
deny → `BLOCK_CARD, CREATE_CASE, FILE_REPORT`; confirm → `CREATE_CASE, CLOSE_NO_FRAUD`;
no_reply → `DECLINE_TRANSACTION, MONITOR_CARD, CREATE_CASE, ESCALATE_TO_ANALYST`. Initial
`VERIFY_WITH_CUSTOMER`… → final `CREATE_CASE, CLOSE_NO_FRAUD`.

**Say:** "Half this job is not blocking good customers. The bank scored this purchase 0.90. Our
model says 0.01, and the device is an ordinary one shared by 37 cards. The customer's answer
would flip the decision, so this time the agent asks. It confirms, and the case closes. No card
blocked on one signal."

---

## 11. 3:15–3:50 — The customer answers, a human signs

**Click:** Sidebar page **Cardholder portal**. Customer ID is already **C04570**.
**Sees:** "Questions from our fraud team: Did you make this purchase? $100.09 on card
C04570-K1, transaction 3450629 (case HHG-017)."
**Click:** **No, it wasn't me**. It shows "You answered: no, it wasn't me", and *Your cases* shows
"Your card will be blocked and a new one sent to you (a member of our fraud team approves this
first)".
**Click:** Sidebar page **app** → **HHG-017** → tab **Evidence & approval**.
**Sees:** Reply preset to **deny**, "The cardholder answered deny in the cardholder portal";
badges `closed_fraud · fraud · p 0.60 → 0.90`; `BLOCK_CARD` **L1** with **Approve / Reject**.
**Click:** Type a note, then **Approve**. An audit-log row appears: time, action, route,
decision, role, analyst, note, and the reply it rests on.

**Say:** "HHG-017 was genuinely balanced, at 0.60, so the agent didn't guess. It asked. The
customer answers in the portal. They only see plain next steps, never scores, and never
anything about a suspicious activity report. Back in the console the reply is already there, and
the policy re-decides: block the card. That's an L1 action, so the agent can't do it alone. A
team lead approves, and the approval is logged with the evidence behind it."

---

## 12. 3:50–4:20 — A case nobody has seen: live

**Click:** Sidebar → **New case**. Transaction ID **3506095**, trigger *Risk-score alert*,
**Investigate**. *(About 20 s: speed it up in the edit.)*
**Sees:** Steps stream in, then the console jumps to **NEW-001**: `fraud · undocumented ·
p = 0.90`, exposure **$276.35**; final `BLOCK_CARD` L1, `FILE_REPORT` L2,
`MONITOR_CONNECTED_CARDS`. Tab **Evidence**: CASE-HHG-014 is among the similar past cases
recalled from memory.

**Say:** "Now a transaction that isn't in the exam. The bank scored it just 0.24, so it would have
passed. Give the agent only the transaction ID and it pulls the card and customer from the graph,
finds the same device ring, now 27 cards, and calls it fraud at 0.90. And it remembers: its
case memory brings back HHG-014, the ring we just saw."

---

## 13. 4:20–4:35 — Sentinel: looking without being asked

**Click:** Switch to `sentinel_cases/SUMMARY.md`.
**Sees:** 15 alerts from sweeping November–December: **1** device ring (SEN-001, the same
profile, **28** cards) and **14** sub-$500 structuring cases ($1,499.85–$2,499.89 each).

**Say:** "It also hunts on its own. A sweep of the last two months raised 15 alerts: the ring
again, and 14 cards buying just under 500 dollars, a pattern the bank never named."

---

## 14. 4:35–4:55 — What's next, and close

**Click:** Back to **Overview** (the Results panel).
**Say:** "Next: real SMS and passcodes, a proper login, community detection, and an agent that
learns from how cases end. 99.3 percent when it decides, 2 frauds missed out of 1,258. One
graph, one policy, every decision explained. Thanks for watching."

---

## If something fails on camera

- **Investigate live / New case errors** ("Failed to start workspace", 403, 502): Savanna is
  asleep or blocking the IP. Cut the segment. Every recorded case works with no connection.
- **Streamlit shows an old page:** press `R` in the browser (rerun) or restart the server.
- **Portal shows no question for C04570:** `audit/replies.jsonl` already holds an answer. Delete
  `audit/` and reload.
- **Over time:** drop segment 7 (Evidence) and shorten 13 (Sentinel) to one sentence.

---

## Appendix A — Every part of the UI

### Sidebar (analyst console, page *app*)

| Element | What it does |
|---|---|
| Page list: *app*, *Cardholder portal* | Switch between the analyst console and the customer's side |
| **Use mock data** | Shows sample cases from `ui/mock/` (for UI work without real output) |
| **Signed in as** | *team lead (L1)* or *fraud manager (L2)*: decides which actions you may approve (§2) |
| **Analyst name** | Written to the audit log with every approval |
| **Case** list | **Overview**, **New case**, the 20 exam cases, then any new cases (NEW-001…); each shows verdict · p · status |

### Overview

| Element | What it shows |
|---|---|
| **Results** tiles | Held-out accuracy: 99.3% decided accuracy, 2 of 1,258 frauds called legitimate, 99.6% fraud-call precision, 92.8% pattern accuracy, model AUC 0.886 vs bank 0.052 |
| Case table | Per case: trigger, verdict, pattern, probability, exposure, SAR yes/no, number of final actions, status |
| Verdict tiles | 10 fraud · 6 legitimate · 4 uncertain |

### Case header (every case)

| Element | What it shows |
|---|---|
| Trigger line | Trigger type and text, flagged transaction, card, customer, the bank's risk score (a reason to look, never a verdict) |
| Badges | Status (open / closed_fraud / closed_legitimate / escalated), verdict, pattern, fraud probability |
| Exposure | Sum of the affected transactions' amounts |
| **Investigate live** | Re-runs the real agent on this trigger (TigerGraph + LLM, about 20–40 s), streams each step, says whether it matches the recorded answer; dry run, nothing written |

### Tabs

| Tab | What it shows |
|---|---|
| **Timeline** | Tool calls, tokens, latency; every step with its tool and result (8 stages: trigger → investigate → gather evidence → assess → evidence gate → actions → explain → case memory) |
| **Courtroom** | Prosecution vs defence claims with strength bars; the calibrated probability on a bar marked with the policy thresholds (0.15, 0.30, 0.70, 0.85) |
| **Evidence** | Every claim with source (graph / customer / document / external), the query or policy section it came from, entity IDs; similar prior cases |
| **Graph** | The case's neighbourhood from TigerGraph: customer, cards, transactions, device profiles, regions, closed and agent cases. Colour = role in the case, shape = entity type |
| **Next best action** | The evidence gate (which request, and the actions each possible reply leads to), evidence requested and the assumed reply, initial vs final actions with approval routes and rule-citing reasons, what changed |
| **Evidence & approval** | Pick the reply that came back and the policy re-decides on the spot: status, verdict, probability, SAR. Preset to the agent's assumption, or to the cardholder's real portal reply. Below it, approve / reject each L1/L2 action; a team lead signs L1, a fraud manager L1 and L2; every decision goes to the audit log |
| **SAR** | Narrative, subjects, total, activity dates, or why no report is required |
| **Summary** | Plain-language case summary, stop reason, raw answer JSON download, and the exact GraphRAG context the LLM saw |

### New case (sidebar)

Transaction ID, trigger (risk-score alert / customer report / analyst request), optional message
and opening time, and a checkbox to write the case to the graph (off by default). The graph
supplies card, customer, amount, time and risk score. The agent runs live, and the console
jumps to the finished case, which has all the tabs above.

### Cardholder portal (page *Cardholder portal*)

| Section | What it does |
|---|---|
| Customer ID | Demo sign-in (a real portal would authenticate); try `C04570` |
| **Questions from our fraud team** | "Did you make this purchase?" for the customer's cases waiting on them; **Yes, it was me** / **No, it wasn't me** go to the analyst console |
| **Your cases** | Plain next steps per case. No probabilities or routes, and nothing about a SAR (it must never be disclosed to its subject) |
| **Report a transaction you don't recognise** | Lists the customer's own recent transactions; reporting one opens a customer-report case that the agent investigates live |

---

## Appendix B — Facts behind each segment

| Segment | Case | Facts shown |
|---|---|---|
| 3–9 | HHG-014 | analyst request · fraud 0.90 · undocumented · $187.33 · 18 tool calls · 14 steps · ring used as New by 19 other cards, 52 ever, 44 closed cases · SAR 2016-11-15 – 2016-11-22 |
| 10 | HHG-010 | bank 0.90 on $1,000.03 · classifier 0.01 · device shared by 37 cards · asks, customer confirms · closed legitimate |
| 11 | HHG-017 | bank 0.57 on $100.09 · agent 0.60, request left pending · deny → `BLOCK_CARD` L1, p 0.90 |
| 12 | txn 3506095 | bank 0.24 on $92.16 · fraud 0.90 · 27 other cards on the ring device · SAR · recalls CASE-HHG-014 · about 21 s |
| 13 | sentinel | 15 alerts: 1 ring (28 cards), 14 structuring |
