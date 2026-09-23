"""GraphRAG step: ground the LLM in connected graph evidence, similar past cases (case memory) and the
policy / typology / regulatory passages, as one compact context block instead of raw query output.

Retrieval goes through the TigerGraph MCP server only (mcp_tools): vector search over ClosedCase +
AgentCase (`similar_cases`) and Doc (`search_docs`), plus `get_node` for the policy rules the policy
engine cited that vector search did not return.
"""
import re

from hhg import llm, mcp_tools

K_CASES = 8
K_DOCS = 8
MAX_CASES = 6        # past cases shown in the context
MAX_DOCS = 7         # passages shown in the context (cited rules and the pattern's typology first)
MAX_IDS = 8          # entity ids shown per evidence line

# customer / card ids of *other* cardholders in past-case notes would invite the LLM to reuse them
_OTHER_IDS = re.compile(r"\bC\d{5}(-K\d)?\b")
# ids and numbers masked in embedded texts, as in scripts/embed_corpus.py (keeps the semantics)
_MASK = re.compile(r"\b(CC-\d+|C\d{5}(-K\d)?|\d[\d,.:-]*)\b")
_KNOWN_PATTERNS = {"card_testing", "card_not_present_fraud", "card_not_present_new_device",
                   "out_of_region_use", "account_takeover"}


def _words(text, n):
    w = str(text or "").split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "")


def _hits(res):
    """Vector-search result -> [{id, type, attributes, distance}] nearest first."""
    dist = res.get("distances") or {}
    hits = [{"id": v["v_id"], "type": v["v_type"], "attributes": v.get("attributes") or {},
             "distance": dist.get(v["v_id"])} for v in res.get("V") or []]
    return sorted(hits, key=lambda h: 9.0 if h["distance"] is None else h["distance"])


def query_text(case_row, findings):
    """Retrieval query: trigger + pattern + the key signals and top prosecution/defence claims."""
    sig = findings.get("signals") or {}
    on = [k for k, v in sig.items() if v is True]
    claims = [e["claim"] for e in (findings.get("prosecution") or [])[:2] + (findings.get("defence") or [])[:1]]
    text = (f"pattern {findings.get('pattern', 'none')}; verdict {findings.get('verdict', 'uncertain')}. "
            f"{findings.get('pattern_reason', '')}. {case_row.get('trigger_type', '')}: "
            f"{case_row.get('trigger_text', '')} Signals: {', '.join(on) or 'none'}. {' '.join(claims)}")
    return _MASK.sub("#", text)


def _rule_doc_ids(findings):
    """Doc ids for the rules policy.decide cited (findings['rule_ids'] may hold 'R5', 'POLICY-R5' or
    whole reason strings) and the typology passage of the identified pattern."""
    ids = []
    for s in findings.get("rule_ids") or []:
        ids += [f"POLICY-R{n}" for n in re.findall(r"\bR(\d{1,2})\b", str(s))]
    if findings.get("pattern") in _KNOWN_PATTERNS:
        ids.append(f"PATTERN-{findings['pattern']}")
    return list(dict.fromkeys(ids))


def _evidence_line(kind, e):
    ids = e.get("entity_ids") or []
    more = f" +{len(ids) - MAX_IDS} more" if len(ids) > MAX_IDS else ""
    return (f"- [{kind} {e.get('score', 0):.2f}] {e['claim']} (ref: {e.get('ref', '')}; "
            f"ids: {', '.join(ids[:MAX_IDS]) or 'none'}{more})")


def build_context(case_row, findings, graph_facts):
    """Retrieve and assemble the GraphRAG context for one case.

    Returns {"context": str, "similar_cases": [{id, type, outcome_or_verdict, pattern, distance}],
             "docs": [{id, title, distance}], "calls": graph calls made here}.
    """
    calls0 = mcp_tools.calls
    qv = llm.embed([query_text(case_row, findings)])[0]
    pattern = findings.get("pattern", "none")

    # ---- case memory: bank's closed cases + the agent's earlier cases (never this case itself)
    hits = [h for h in _hits(mcp_tools.run_query("similar_cases", {"qv": qv, "k": K_CASES}))
            if not (h["type"] == "AgentCase" and (h["attributes"].get("case_id") == case_row.get("case_id")
                                                  or str(h["attributes"].get("created_at", ""))[:19]
                                                  >= str(case_row.get("opened_at", ""))[:19]))]  # no look-ahead
    hits.sort(key=lambda h: h["attributes"].get("pattern") != pattern)  # stable: same pattern first
    hits = hits[:MAX_CASES]
    similar = [{"id": h["id"], "type": h["type"], "pattern": h["attributes"].get("pattern", ""),
                "outcome_or_verdict": h["attributes"].get("outcome" if h["type"] == "ClosedCase" else "verdict", ""),
                "distance": h["distance"]} for h in hits]

    # ---- documents: cited rules + pattern typology first, then nearest passages
    found = _hits(mcp_tools.run_query("search_docs", {"qv": qv, "k": K_DOCS}))
    by_id = {h["id"]: h for h in found}
    wanted = _rule_doc_ids(findings)
    for doc_id in wanted:
        if doc_id not in by_id:
            try:
                node = mcp_tools.call("get_node", vertex_type="Doc", vertex_id=doc_id)
            except mcp_tools.MCPError:  # not in the graph: skip rather than invent
                continue
            by_id[doc_id] = {"id": doc_id, "type": "Doc", "attributes": node.get("attributes") or {}, "distance": None}
    ordered = [by_id[i] for i in wanted if i in by_id] + [h for h in found if h["id"] not in wanted]
    docs = ordered[:MAX_DOCS]

    # ---- context block
    t = case_row
    ep = findings.get("episode") or {}
    lines = ["CASE",
             f"{t.get('case_id')} opened {t.get('opened_at')} by {t.get('trigger_type')} trigger: \"{t.get('trigger_text', '')}\"",
             f"Flagged txn {t.get('flagged_txn_id')} on card {t.get('card_id')} (customer {t.get('customer_id')})."
             + (f" Bank risk score {t['risk_score']} is a reason to look, not a verdict (§0)." if t.get("risk_score") not in (None, "") else ""),
             f"Graph analysis: pattern {pattern} ({findings.get('pattern_reason', '')}); fraud probability "
             f"{findings.get('fraud_probability', 0):.2f}; verdict {findings.get('verdict', 'uncertain')}; "
             f"{len(ep.get('affected_txn_ids') or [])} affected txns, first {ep.get('first_suspicious_txn_id') or 'none'}, "
             f"exposure ${ep.get('exposure_usd', 0):,.2f}.",
             "", "GRAPH EVIDENCE"]
    lines += [f"- {g}" for g in graph_facts]
    lines += [_evidence_line("prosecution", e) for e in findings.get("prosecution") or []]
    lines += [_evidence_line("defence", e) for e in findings.get("defence") or []]

    lines += ["", "SIMILAR PAST CASES (vector search over closed and agent cases; same pattern first)"]
    for h in hits:
        a = h["attributes"]
        note = a.get("notes", "") if h["type"] == "ClosedCase" else a.get("summary", "")
        note = _OTHER_IDS.sub("[other id]", re.sub(r"^Case CC-\d+:\s*", "", note))
        d = "" if h["distance"] is None else f", distance {h['distance']:.3f}"
        lines.append(f"- [{h['id']}] {h['type']} {a.get('outcome') or a.get('verdict', '')}, pattern "
                     f"{a.get('pattern', '')}{d}: {_words(note, 45)}")
    if not hits:
        lines.append("- none retrieved")

    lines += ["", "POLICY & GUIDANCE"]
    for h in docs:
        a = h["attributes"]
        lines.append(f"- [{h['id']}] {a.get('title', '')}: {_words(a.get('text', ''), 70)}")
    if not docs:
        lines.append("- none retrieved")

    lines += ["", "INSTRUCTIONS",
              "Use only the facts above. Cite the ids in square brackets and the txn/card/device ids shown; "
              "never invent an id, amount or date. Past cases are memory, not this customer's activity: their "
              "ids are not connected cards. The bank risk score is not a verdict. Actions come from the policy "
              "engine: explain them, do not change them."]

    return {"context": "\n".join(lines), "similar_cases": similar,
            "docs": [{"id": h["id"], "title": h["attributes"].get("title", ""), "distance": h["distance"]} for h in docs],
            "calls": mcp_tools.calls - calls0}


def case_embedding_text(answer):
    """Text embedded for a finished AgentCase, in the same shape as the closed-case texts
    (scripts/embed_corpus.py case_text) so later investigations retrieve it next to them."""
    c = answer["case"]
    acts = "|".join(a["action"] for a in answer.get("next_best_actions", {}).get("final", []))
    claims = " ".join(e["claim"] for e in c.get("evidence", [])[:4])
    note = _MASK.sub("#", f"{c.get('pattern_description', '')} {c.get('summary', '')} {claims}".strip())
    return f"{c['verdict']}; pattern {c['pattern']}; actions {acts}; report {int(answer.get('sar', {}).get('file', False))}. {note}"
