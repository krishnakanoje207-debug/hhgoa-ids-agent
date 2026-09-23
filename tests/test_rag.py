import unittest
from unittest import mock

from hhg import mcp_tools, rag

CASE = {"case_id": "HHG-017", "opened_at": "2016-11-14 11:00:00", "trigger_type": "risk_score",
        "trigger_text": "Real-time model scored transaction T0412883 ($259.98, online) at 0.61. Review and decide.",
        "flagged_txn_id": "T0412883", "card_id": "C00377-K1", "customer_id": "C00377", "risk_score": 0.61}
FINDINGS = {
    "pattern": "card_testing", "pattern_reason": ">=3 small online authorizations within an hour, then a larger purchase",
    "fraud_probability": 0.9, "verdict": "fraud",
    "episode": {"affected_txn_ids": ["T0412877", "T0412878", "T0412879", "T0412883"],
                "first_suspicious_txn_id": "T0412877", "exposure_usd": 268.43},
    "signals": {"card_testing": True, "new_device": True, "trip_signature": False, "flag_score": 0.93},
    "prosecution": [{"claim": "3 online authorizations under $10.00 within an hour then larger purchase(s) $259.98",
                     "score": 0.9, "entity_ids": ["T0412877", "T0412878", "T0412879", "T0412883"],
                     "ref": "query:card_window(card_id=C00377-K1, hours=1)"}],
    "defence": [{"claim": "Flagged device D000731 was already used on this card before", "score": 0.5,
                 "entity_ids": ["T0412883"], "ref": "query:card_history(card_id=C00377-K1, window=60d)"}],
    "rule_ids": ["R5: card-testing sequence observed", "R1 not triggered", "R2"],
}
FACTS = ["Device profile D000731 was used as New by card C00877-K1 on 2016-11-12 (query:device_neighbors)"]

SIMILAR = {
    "V": [
        {"v_id": "CC-0200", "v_type": "ClosedCase", "attributes": {"outcome": "confirmed_fraud", "pattern": "card_not_present_fraud",
         "notes": "Case CC-0200: cardholder C01111 reported unrecognized activity on card C01111-K1. Online purchases."}},
        {"v_id": "CC-0141", "v_type": "ClosedCase", "attributes": {"outcome": "confirmed_fraud", "pattern": "card_testing",
         "notes": "Case CC-0141: cardholder C02222 reported activity on card C02222-K1. Three tiny authorizations then a purchase."}},
        {"v_id": "AC-HHG-017", "v_type": "AgentCase", "attributes": {"case_id": "HHG-017", "verdict": "fraud",
         "pattern": "card_testing", "summary": "this very case from an earlier run"}},
        {"v_id": "AC-HHG-003", "v_type": "AgentCase", "attributes": {"case_id": "HHG-003", "verdict": "fraud",
         "pattern": "card_testing", "summary": "Card testing then a $300 purchase."}},
    ],
    "distances": {"CC-0200": 0.05, "CC-0141": 0.10, "AC-HHG-017": 0.01, "AC-HHG-003": 0.20},
}
DOCS = {
    "V": [
        {"v_id": "FINCEN-SAR-NARRATIVE-03", "v_type": "Doc", "attributes": {"title": "SAR narrative: who what when", "text": "Describe who, what, when."}},
        {"v_id": "PATTERN-card_testing", "v_type": "Doc", "attributes": {"title": "Card testing", "text": "Three or more tiny online authorizations."}},
    ],
    "distances": {"FINCEN-SAR-NARRATIVE-03": 0.2, "PATTERN-card_testing": 0.1},
}
NODES = {"POLICY-R5": {"title": "R5 card testing", "text": "Decline and step up; block if a purchase over $100 cleared."},
         "POLICY-R2": {"title": "R2 customer denies", "text": "Block the card and open a case."}}


def fake_call(tool, **args):
    mcp_tools.calls += 1
    if args["vertex_id"] not in NODES:
        raise mcp_tools.MCPError(f"{args['vertex_id']} is not valid Doc vertex")
    return {"v_id": args["vertex_id"], "attributes": NODES[args["vertex_id"]]}


def fake_query(name, params):
    mcp_tools.calls += 1
    assert len(params["qv"]) == 384 and params["k"] == 8
    return {"similar_cases": SIMILAR, "search_docs": DOCS}[name]


class BuildContextTest(unittest.TestCase):
    def run_rag(self, findings=FINDINGS, facts=FACTS):
        with mock.patch.object(rag.llm, "embed", return_value=[[0.1] * 384]) as emb, \
             mock.patch.object(mcp_tools, "run_query", side_effect=fake_query), \
             mock.patch.object(mcp_tools, "call", side_effect=fake_call):
            out = rag.build_context(CASE, findings, facts)
        return out, emb.call_args[0][0][0]

    def test_sections_and_ids(self):
        out, qtext = self.run_rag()
        ctx = out["context"]
        heads = ["CASE", "GRAPH EVIDENCE", "SIMILAR PAST CASES", "POLICY & GUIDANCE", "INSTRUCTIONS"]
        pos = [ctx.index(h) for h in heads]
        self.assertEqual(pos, sorted(pos))
        self.assertIn(FACTS[0], ctx)
        self.assertIn("ref: query:card_window(card_id=C00377-K1, hours=1)", ctx)
        self.assertIn("T0412877", ctx)
        self.assertIn("[defence 0.50]", ctx)
        self.assertIn("card_testing", qtext)
        self.assertNotIn("C00377", qtext)  # ids masked in the retrieval query
        # other cardholders' ids in past-case notes are masked
        self.assertNotIn("C02222", ctx)
        self.assertLess(len(ctx.split()), 1800)

    def test_similar_cases_ranked_and_self_excluded(self):
        out, _ = self.run_rag()
        ids = [s["id"] for s in out["similar_cases"]]
        self.assertEqual(ids, ["CC-0141", "AC-HHG-003", "CC-0200"])  # same pattern first, then distance
        self.assertEqual(out["similar_cases"][0], {"id": "CC-0141", "type": "ClosedCase", "outcome_or_verdict":
                                                   "confirmed_fraud", "pattern": "card_testing", "distance": 0.10})
        self.assertEqual(out["similar_cases"][1]["outcome_or_verdict"], "fraud")
        self.assertNotIn("AC-HHG-017", out["context"])

    def test_cited_rules_fetched_first(self):
        out, _ = self.run_rag()
        ids = [d["id"] for d in out["docs"]]
        # R5 and R2 fetched by get_node, R1 missing in the graph is skipped, pattern doc came from search
        self.assertEqual(ids, ["POLICY-R5", "POLICY-R2", "PATTERN-card_testing", "FINCEN-SAR-NARRATIVE-03"])
        self.assertIsNone(out["docs"][0]["distance"])
        self.assertEqual(out["calls"], 2 + 3)  # two vector searches + three get_node (R5, R1, R2)
        self.assertIn("[POLICY-R5] R5 card testing:", out["context"])

    def test_budget_with_large_inputs(self):
        big = dict(FINDINGS, prosecution=FINDINGS["prosecution"] * 12, defence=FINDINGS["defence"] * 6)
        out, _ = self.run_rag(big, FACTS * 15)
        self.assertLess(len(out["context"].split()), 1800)


class NoLookAheadTest(unittest.TestCase):
    def test_agent_cases_created_at_or_after_opening_excluded(self):
        def ac(cid, created):
            return {"v_id": f"AC-{cid}", "v_type": "AgentCase",
                    "attributes": {"case_id": cid, "verdict": "fraud", "pattern": "card_testing",
                                   "summary": "s", "created_at": created}}
        sim = {"V": [SIMILAR["V"][1], ac("HHG-017", "2016-11-01 00:00:00"),  # own case, even if earlier
                     ac("HHG-003", "2016-11-14 10:59:59"), ac("HHG-009", CASE["opened_at"]),
                     ac("HHG-010", "2016-12-01 00:00:00")],
               "distances": {"CC-0141": 0.1, "AC-HHG-017": 0.01, "AC-HHG-003": 0.2, "AC-HHG-009": 0.02,
                             "AC-HHG-010": 0.03}}
        with mock.patch.object(rag.llm, "embed", return_value=[[0.1] * 384]), \
             mock.patch.object(mcp_tools, "run_query", side_effect=lambda n, p: sim if n == "similar_cases" else DOCS), \
             mock.patch.object(mcp_tools, "call", side_effect=fake_call):
            out = rag.build_context(CASE, FINDINGS, FACTS)
        self.assertEqual([s["id"] for s in out["similar_cases"]], ["CC-0141", "AC-HHG-003"])
        for gone in ("AC-HHG-017", "AC-HHG-009", "AC-HHG-010"):
            self.assertNotIn(gone, out["context"])


class EmbeddingTextTest(unittest.TestCase):
    def test_case_embedding_text(self):
        ans = {"case": {"verdict": "fraud", "pattern": "undocumented", "pattern_description": "Device ring across cards.",
                        "summary": "Card C00377-K1 hit by ring; CC-0141 similar; $268.43.",
                        "evidence": [{"claim": "Shared device used as New by 5 cards"}]},
               "next_best_actions": {"final": [{"action": "BLOCK_CARD"}, {"action": "FILE_REPORT"}]},
               "sar": {"file": True}}
        text = rag.case_embedding_text(ans)
        self.assertTrue(text.startswith("fraud; pattern undocumented; actions BLOCK_CARD|FILE_REPORT; report 1."))
        self.assertIn("Device ring across cards.", text)
        self.assertNotIn("C00377", text)
        self.assertNotIn("CC-0141", text)


if __name__ == "__main__":
    unittest.main()
