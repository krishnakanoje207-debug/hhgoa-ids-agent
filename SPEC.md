# HHGOA build contract

Source of truth for the task: `dataset/README.md` (policy §0–§7, Answer Format, the 20 cases).
If this file and the README disagree, the README wins.

## Hard rules
- Never download or use the original Kaggle / IEEE-CIS files. Disqualification.
- Never invent IDs, columns, action names, routes or TigerGraph APIs. Every ID in output must exist in the dataset.
- Action identifiers and routes exactly as README Fraud Policy §1–§2.
- Work on D: only (venv `D:\hhgoa\.venv`, pip cache `D:\hhgoa\.cache\pip`). Python: `D:\hhgoa\.venv\Scripts\python.exe`.
- Minimal code, no speculative abstractions. Stdlib + pandas + openai + pyTigerGraph + streamlit only.

## Layout
```
src/hhg/config.py      load .env (python-dotenv)
src/hhg/tg.py          TigerGraph REST client (token via secret, run installed query, upsert) — owner: lead
src/hhg/policy.py      deterministic Fraud Policy engine (pure functions) — owner: policy agent
src/hhg/validate.py    answer-file validator (CLI: python -m hhg.validate cases/) — owner: policy agent
src/hhg/llm.py         OpenAI-compatible client (Gemini/Groq) + deterministic fallback text — owner: lead
src/hhg/rag.py         GraphRAG retrieval (TigerGraph vectors + graph evidence -> context block) — owner: lead
src/hhg/agent.py       investigation loop — owner: lead
gsql/                  schema + installed queries
scripts/               prepare_data.py, load_graph.py, run_benchmark.py, sentinel.py
knowledge/chunks.jsonl GraphRAG corpus (policy, patterns, regulatory excerpts) — owner: knowledge agent
cases/HHG-0xx.json     the 20 answers
ui/app.py              Streamlit analyst console
tests/                 unittest tests (python -m unittest discover -s tests)
```
Run code with `PYTHONPATH=src`.

## Findings object (produced by agent investigation, consumed by policy.py)
A plain dict. Keys:

| key | type | meaning |
|---|---|---|
| `trigger_type` | `risk_score`\|`customer_report`\|`analyst_request` | from case pack |
| `fraud_probability` | float 0–1 | calibrated, from graph evidence |
| `verdict` | `fraud`\|`legitimate`\|`uncertain` | |
| `pattern` | README pattern enum | `card_testing`, `card_not_present_fraud`, `card_not_present_new_device`, `out_of_region_use`, `account_takeover`, `undocumented`, `none` |
| `independent_evidence` | int | count of independent evidence items supporting the verdict (policy §6 needs ≥2) |
| `single_signal` | bool | case rests on one signal only (R1) |
| `evidence_conflicts` | bool | prosecution and defence evidence both strong (R8) |
| `exposure_usd` | float | sum of abs amounts of affected txns (§4) |
| `card_testing` | bool | ≥3 small online auths within 1h then larger purchase (R5) |
| `cleared_purchase_over_100` | bool | in a testing sequence a >$100 purchase already went through (R5) |
| `shared_origin` | null or `{"kind": "device"\|"region"\|"email", "id": str, "card_ids": [str]}` | several cards show fraud from same element (R6) |
| `connects_to_other_fraud` | bool | linked to another card's/customer's fraud (R2, §3a) |
| `recurring_match` | bool | disputed charge matches own recurring pattern (R7) |
| `customer_cards_confirmed_fraud` | int | how many of this customer's cards show confirmed fraud (R10) |
| `credentials_compromised` | bool | (R10) |
| `customer_response` | null\|`deny`\|`confirm`\|`no_reply` | assumed reply to customer_validation (R2/R3/R4) |
| `step_up_result` | null\|`pass`\|`fail` | assumed step-up result |

## policy.py public API (pure, no I/O)
- `route(action: str, exposure_usd: float) -> str` — `auto`/`L1`/`L2` per §2.
- `decide(f: dict) -> list[dict]` — ordered `[{"action","route","reason"}]`, every reason cites R-numbers / §.
- `needs_case(f) -> bool` (§3a), `needs_sar(f, actions) -> (bool, reason)` (§3a).
- `should_stop(f) -> (bool, reason)` (§6).
- `evidence_gate(f) -> dict|None` — the "decision-flip" test: re-run `decide` under each possible response of each evidence type (customer_validation: deny/confirm/no_reply; step_up_auth: pass/fail; analyst_info). If no response can change the action set → None (stop, "no response can change the decision"). Otherwise return the cheapest decisive request `{"type", "why", "outcomes": {response: [actions]}}`.
- `status_for(f, final_actions) -> str` — `open`\|`closed_fraud`\|`closed_legitimate`\|`escalated`.

## Answer file
Exactly the README "Answer Format" schema; copy the README example as the template.

## Trace file (agent → UI), `cases/traces/<case_id>.json`
```json
{
  "case_id": "HHG-014",
  "trigger": {"case_id": "...", "opened_at": "...", "trigger_type": "...", "trigger_text": "...", "flagged_txn_id": "...", "card_id": "...", "customer_id": "...", "risk_score": 0.61},
  "steps": [{"step": 1, "name": "Trigger received", "tool": "tigergraph__run_installed_query" , "args": {}, "summary": "one line", "ms": 812}],
  "hypotheses": {
    "prosecution": [{"claim": "...", "score": 0.8, "entity_ids": ["..."], "ref": "query:device_neighbors(...)"}],
    "defence":     [{"claim": "...", "score": 0.3, "entity_ids": ["..."], "ref": "query:region_history(...)"}]
  },
  "probability": {"initial": 0.62, "final": 0.9, "features": {"name": 1.0}},
  "evidence_gate": {"type": "customer_validation", "why": "...", "outcomes": {"deny": ["BLOCK_CARD"], "confirm": ["CLOSE_NO_FRAUD"]}},
  "graph": {"nodes": [{"id": "C13487-K1", "type": "Card", "label": "C13487-K1", "flag": "subject|suspicious|cleared|normal"}],
            "edges": [{"src": "...", "dst": "...", "type": "FROM_DEVICE"}]},
  "rag_context": "the exact context block given to the LLM"
}
```
`evidence_gate` may be null. `tool` may be null for non-tool steps.
