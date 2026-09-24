# Building a fraud investigator that argues with itself

*Technical write-up for the TigerGraph Agentic Fraud Investigation hackathon (Hacker House Goa).*

> **The numbers, up front.** On 1,376 of the bank's own closed cases that nothing was fitted on:
> **99.3%** verdict accuracy when the agent decides, only **2 of 1,258** frauds called
> legitimate, **99.6%** of its fraud calls right, and the fraud pattern named correctly
> **92.8%** of the time. Our model scores **0.886** AUC where the bank's own risk score scores
> **0.052**. All **20 of 20** exam answers are valid and written back to the graph.

## What we built

A fraud team's real job isn't scoring transactions — a model already does that, badly, at the
edges. The job is investigation: take an alert, figure out how far it goes, decide whether it's
actually fraud, and pick a defensible action. That's what we built an agent to do.

Given a trigger — a risk-score alert, a customer's "I never made this purchase," or an
analyst's "these cards are all touching the same weird device" — the agent opens a case, pulls
the relevant neighbourhood out of a TigerGraph knowledge graph (the card's history, who else
shares its device or billing region, similar past cases), and argues both sides of the question
before deciding anything. A deterministic policy engine — not the LLM — turns that evidence into
a recommendation and an approval route. If the policy engine can find evidence that would
actually change the recommendation, the agent asks for it; if nothing would, it stops. Every
closed case gets written back into the graph, so the next investigation that touches the same
device or customer finds it.

We ran this against IEEE-CIS card transaction data (590,742 transactions, ~13,500 customers,
six months, no fraud label — replaced with a risk score the brief tells you not to trust), with
5,565 of the bank's own closed investigations as labelled history and 20 held-out cases as the
exam. Two things along the way surprised us, and we'll get to both.

## Architecture

Five pieces, one graph. **TigerGraph Savanna** holds the graph *and* the vectors — customers,
cards, transactions, device profiles, billing regions, closed cases, and the agent's own cases,
all in one place, with 384-dimension embeddings (`BAAI/bge-small-en-v1.5`, run locally) as vector attributes on `ClosedCase`, `Doc`, and
`AgentCase` vertices rather than a bolted-on vector database. **TigerGraph MCP** is the agent's
only door into that graph — no raw driver call anywhere in its code path, and the allowlist is
deliberately short: the 8 installed queries, neighbour lookups, vector search, and node/edge
writes for case memory. Nothing that can touch schema.

A **GraphRAG context builder** takes what those queries return — a card's transaction window, a
device's other cardholders, the nearest closed cases by embedding, the nearest policy and
regulatory passages — and condenses it into one context block. The brief is explicit that the
LLM should get *context*, not raw data, so the query layer makes that the easy path:
`device_neighbors` doesn't return a table of transactions, it returns which cards touched a
device profile in a window and what happened to them. **The LLM** (Gemini Flash-Lite, free
tier, OpenAI-compatible endpoint) plans which tool to call next and writes prose — the case
summary, the SAR narrative, an undocumented-pattern description. It never sees a decision to
make. That's the **policy engine**'s job: `policy.py` is pure Python, no LLM call inside, taking
a plain findings dict — probability, pattern, independent-evidence count, shared-origin flags —
and returning the action list, the approval route for each, whether a case or SAR is warranted,
and whether to keep investigating. Same inputs, same outputs, every time — which is what makes
the answer files auditable: every action carries a reason that cites a rule number.

## How TigerGraph is used

We started from the README's suggested schema — `Customer`, `Card`, `Transaction`,
`DeviceProfile`, `EmailDomain`, `BillingRegion`, `ClosedCase` — and extended it with `AgentCase`
(the agent's own case memory) and `Doc` (the GraphRAG corpus: policy text, the five documented
patterns, and chunks from FinCEN's SAR narrative guidance, its account-takeover and
identity-fraud advisories, the FFIEC manual, and FATF's cyber-enabled-fraud report). Edges are
undirected, because an investigation walks them both ways — card-to-device is the same query as
device-to-every-card-it-touched. The first real engineering decision was `card_id`: the dataset
has no card ID column, only a customer ID and anonymized card-network/type fields, so we derived
`card_id = (customer_id, card4, card6)` and checked it against the card on every transaction of
all 5,565 closed cases and the 20 case-pack rows before trusting it: 14,975 of 14,975 matched.

Eight installed GSQL queries do the investigation work, each scoped to a question rather than a
table: `card_history` (a card's own timeline), `device_neighbors` (who else shares a device —
the query that lit up the HHG-014 ring: a Samsung SM-G935F behind Chrome Android and an
anonymous proxy, used as a new device by 19 other cards in the same window, by only 52 cards
ever, with 44 closed cases already linked to them),
`region_cluster` (who's new to a billing region), `customer_cases` (R10's "two cards already
confirmed" check), and two `vectorSearch` queries — `similar_cases` and `search_docs` — the
GraphRAG retrieval itself. Two more, `device_ring_scan` and `near_threshold_scan`, don't answer
a single case; they scan the whole November–December window for device profiles or near-$500
purchase clusters recurring across cards. That's sentinel mode, and how we found two typologies
outside the bank's five documented patterns: the device ring, and sub-$500 structuring (four
purchases in thirty minutes on one card in HHG-006, each just under $500, $1,906.07 in total).

We chose targeted GSQL pattern queries plus native `vectorSearch` over the graph-algorithm
library — no Louvain, no generic community detection. An unsupervised cluster ID is hard to put
in a SAR narrative; "card C13487-K1 used device profile `SM-G935F Build/NRD90M | Android 7.0 |
chrome 62.0 for android | 1920x1080` as new, behind an anonymous proxy, like 19 other cards that
window; 44 closed cases, CC-0020 among them, touch its cards" is a sentence a human can verify,
"community 17" is not.

The last piece is a gradient-boosting model trained on the bank's own closed cases — confirmed
fraud as positive, cleared as negative, and a 15% sample of all unlabelled July–October
transactions as negatives — validated on a strict time split (train on cases opened July–August,
test on September–October, so nothing resembles the November–December exam). That sample
includes transactions on cards that have cases: an earlier version left those cards out, and the
model promptly learned "this card has case history" as a fraud signal, when the closed cases
already hold about all the fraud. Its score is written back as `Txn.model_score`, read through
MCP like any other evidence. Here's the first surprise: time-split AUC on confirmed-vs-cleared
came out at 0.886 (0.951 on all test transactions), while the bank's own risk score on the
*same* transactions scored 0.052 — not near 0.5, near zero. The bank's alerting model
is anti-correlated with its own analysts' verdicts where those verdicts exist. We weren't
looking for that; it fell out of the validation step, and it's a good demonstration of why the
policy treats a risk score as "a reason to look, never a verdict."

We measured the whole verdict stage on 1,376 closed September cases that nothing was fitted on.
When the agent commits to fraud or legitimate it is right 99.3% of the time (95.8%
class-balanced), and it commits on 55% of cases. The rest stay uncertain and go to
verification. Only 2 of 1,258 confirmed frauds were called legitimate, its fraud calls are
right 99.6% of the time, and it names the pattern correctly on 92.8% of confirmed fraud.

It took two fixes, both found by this evaluation, to get there; decided accuracy was 86.0% and
121 frauds were called legitimate before them. Our "recurring charge" defence matched any
same-amount charges that happened to be about a month apart and overrode the verdict to
legitimate. In the bank's history those matches were fraud every time: repeat charges on a stolen
card look "recurring". The second fix was about what may clear a case at all. A low probability
plus "looks like a trip" still hid fraud, while the one defence the cleared cases back is a new
phone. So the agent now clears a case on its own only with that evidence. Otherwise it asks the
customer, which costs one message and never blocks anyone. Both fixes held on the months the
model was fitted on as well as on the holdout.

Two more pieces of evidence come straight from the graph rather than from the model.

**Account history, read from the graph.** A "card" in this data mixes several underlying
accounts, so the agent reconstructs the flagged transaction's account (card, billing region, and
transaction date minus `D1` within a day) and asks, through MCP `get_neighbors` on the card's
closed cases, whether any earlier transaction of that account was ever in one. A clean account —
five or more earlier transactions at least a week before the flag, none in any case — caps the
probability at 0.15 (0.17% of in-person transactions on such accounts were fraud, n=18,055); an
account with a transaction in a confirmed case is prosecution evidence and, with a bank risk
score ≥0.5, floors it at 0.9 (97.2% fraud, n=431). HHG-001 is the case this changed: a 0.79
model score in a region away from home, but a clean account in region 444. That brings it down to
0.15, and it is closed legitimate once the customer confirms.

**Rare-device shared origin.** When the evidence already leans fraud, the agent checks whether
the flagged device profile is rare (20 cards ever or fewer) and whether the same
purchaser/recipient email pair turned up on two or more other cards from a week before the flag
to opening. In August–October, 47.8% of such matches were fraud versus 11.2% without. It doesn't
move the probability; it names connected cards, adds `MONITOR_CONNECTED_CARDS`, and triggers a
report — HHG-019 links C06224-K2 and C11309-K1 this way.

## Agentic capabilities

Three things we'd call genuinely agentic, not a scripted pipeline with an LLM sprinkled on top.

**The courtroom.** For every case, the agent builds a prosecution case and a defence case in
parallel, testing the defence as hard as the prosecution. The bank's own cleared cases gave us
the defence archetypes for free — a trip, a new phone, a recurring charge, a customer who says
they meant to make the purchase. An agent that only looks for fraud finds it everywhere; half of
this exam is legitimate, and the policy scores an agent that blocks everything badly.

**The decision-flip evidence gate** is the piece we're most pleased with. Instead of "if
uncertain, ask the customer" as a blanket rule, `evidence_gate()` simulates every possible
answer to every evidence type the current recommendation would justify asking for — confirm,
deny, no reply; step-up pass or fail — and re-runs the policy on each simulated outcome. If no
possible answer changes the action set, the agent doesn't ask: the policy's stopping rule treats
"further steps are unlikely to change the decision" as a first-class reason to stop, not an
afterthought. Because replies are simulated, there's a second guard: when the probability sits
between 0.30 and 0.70, a simulated answer would only echo the agent's own guess, so it records
the request and assumes nothing — the case stays open or escalated as `uncertain`. Four of the
twenty benchmark cases end that way. Outside the band it simulates the reply the evidence points
to and says so in the answer file.

Those four open cases are where the console earns its keep. Each trace stores the agent's
findings from before it asked for anything, so an analyst can enter the reply that actually came
back. If the customer denies, confirms or goes silent, the policy engine re-decides then and
there: actions, approval routes, case status, whether a SAR is due. The agent may execute only
the `auto` actions. A card block or a SAR waits for a team lead or fraud manager to approve it
in the console. Each sign-off is appended to an audit log, together with the evidence replies it
was based on.

The customer has a screen too. In the cardholder portal a customer answers "Did you make this
purchase?" for their own open cases, and the analyst console picks up that answer. They can also
report a transaction they don't recognise, which opens a new case that the agent investigates
live. Customers only ever see plain next steps. A SAR is never disclosed to its subject, so the
portal says nothing about one. An analyst can likewise open a case from any transaction ID: the
graph supplies the card, customer, amount and risk score, and the agent does the rest.

**Case memory that compounds.** Every closed case becomes an `AgentCase` vertex with edges to
the transactions, cards, devices, closed cases, and documents it relied on, plus its own
embedding. The next investigation's `similar_cases` query searches both the bank's original
5,565 cases and every case this agent has already written — a device ring found on case 3 is
retrievable evidence by case 4, no batch reprocessing required. Only earlier ones, though:
`AgentCase`s created at or after a case's `opened_at` are excluded from its retrieval, so memory
never leaks the future.

## What we learned

Building the policy engine before touching the LLM was the right call, even though it felt
backwards at first — we wrote `policy.py` and its tests against the README's rules using
hand-picked evidence dicts, before the agent or the graph existed. That gave us ground truth to
check the agent's findings-assembly against: if a case felt like it should end in `BLOCK_CARD`
and `policy.decide()` disagreed, the bug was in evidence gathering, not the rules.

The `card_id` derivation and the risk-score inversion taught the same lesson: read the data
before trusting the brief's summary of it. We expected "a risk score, an input not an answer" to
mean "sometimes wrong," not inverted on the transactions where ground truth exists — a finding
worth reporting to the bank on its own. The same goes for our own features: a trip signature
that looked like obvious defence evidence fired on 71% of confirmed out-of-region fraud cases
and only 8% of cleared travel, so we kept it as a stated defence point but took it out of the
calibration fit, which would otherwise have learned "trip" as a fraud signal. We also learned to respect the free tier early: Savanna's
auto-resume adds real latency to a cold first query and 502/503s through several retries before
answering, so the retry loop went into the REST client on day one instead of getting discovered
mid-demo.

## What we'd improve with more time

We had a few days, so we cut things. Here is what we left out, why, and what we would build next.

### What we cut for time

**Real evidence channels.** The agent decides *whether* to ask the customer, the cardholder or an
analyst, but the replies are simulated, as the brief allows. A demo cardholder portal and the
analyst console take real answers, and the policy engine decides again. But the portal's sign-in
is a demo, and nothing sends an SMS, runs a real one-time passcode or waits on an inbox. R4's timers ("no reply within 24 hours", "monitor
for 72 hours") are recorded as actions. They are not running clocks.

**Real sign-in and a tamper-proof audit trail.** Only a person can approve `L1` and `L2` actions,
but the console's "signed in as" is a dropdown, not a login. Approvals go to a local
append-only file, not into TigerGraph. No hash chain protects it, and an approved `BLOCK_CARD`
does not yet move the case's status in the graph.

**A live pipeline.** "Investigate live" runs the real agent against TigerGraph on demand, as a
dry run. There is no alert stream feeding it and nothing runs it on a schedule: the 20 cases and
the sentinel sweep are batch runs.

**Graph algorithms.** We chose targeted GSQL pattern queries over TigerGraph's algorithm library
because their output can be read and checked in a SAR. We never ran Louvain or connected
components over the device/region/email co-occurrence graph. That run would show whether our
"shared origin" and ring rules miss rings that never cross `min_cards` in a single window.

**Better evidence for "legitimate".** This is the biggest gap in accuracy. The agent now almost
never clears a fraud (2 of 1,258 in the September holdout), but it gets there by asking the
customer in 45% of cases. The frauds it used to clear look like cleared cases on every feature
we have. The trip defence especially is unreliable. To clear more cases on the graph alone we
would need data we did not build: device age, when a phone number, email or address last changed,
travel confirmations, and a merchant ID. The dataset has none. R7's "same merchant" is
approximated by product code plus amount.

**Evaluating the whole loop.** We measured the verdict stage on 1,376 held-out closed cases, but
those cases do not record which actions were taken. The quality of actions and evidence requests
is therefore checked only by the policy tests and the 20 exam cases, never against history.

**The knowledge corpus.** The corpus has 68 passages from a curated subset of the regulatory
sources the README lists. `knowledge/SOURCES.md` records what we skipped, mostly FATF documents
further from card fraud. A larger corpus would sharpen SAR narratives for cases on the edge of a
documented pattern.

### Future scope

**Learn from outcomes, not just retrieve them.** Every analyst decision and every real customer
reply is a label. Write them back onto the `AgentCase` vertex, re-fit the calibration from them
on a schedule, and let `similar_cases` weigh how a similar case *ended* as well as how it looked.
Today case memory is retrieval. With outcomes it would make the next decision better.

**The production path the brief sketches.** Payment events arrive on a stream, get scored in
real time, and the agent investigates. The graph supplies context, the policy and approval
engine decides, action systems execute, and everything lands in an immutable audit log and case
memory. Around that: OAuth/RBAC for analysts, a four-eyes rule for `L2` actions, a secrets
manager, and OpenTelemetry traces for every tool call and token.

**Graph intelligence.** Next come community detection, entity resolution that links customers
across emails, devices and addresses (our derived `card_id` is a stopgap), and graph embeddings
as model features. Scoring could move into GSQL accumulators so the graph scores at query time
instead of reading a precomputed `model_score`.

**An analyst workbench.** A case queue with SLA timers, reassignment and workload views. Sentinel
finds would go into a human triage queue instead of a folder. A shadow mode would run the agent
beside live analysts and measure how often they agree before it is trusted with more `auto`
actions.

**Ask why the bank's score is inverted.** On transactions with ground truth the bank's risk score
has an AUC of about 0.05. That is worth a study of its own, by product code, amount band and
channel, before anyone trusts either model blindly.

**Scale.** A paid Savanna tier, load tests with many concurrent investigations, and a cache for
the device and region neighbourhoods that most alerts share.

---

Code: https://github.com/krishnakanoje207-debug/hhgoa-ids-agent · Demo: https://drive.google.com/file/d/16rMjGdsbA4KBOAKjSAZYw7p_FWWT6k_b/view
