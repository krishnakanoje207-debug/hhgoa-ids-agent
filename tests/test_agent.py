"""investigate() end to end with mocked graph (run_query), analytics, LLM and GraphRAG."""
import unittest
from unittest import mock

from hhg import agent, analytics, llm, mcp_tools, rag
from hhg.validate import _sentences, validate_answer


def tx(i, ts, amt, ch="online", ms=0.1, dev="", st="", proxy="", addr1="204.0", product="W"):
    a = {"id": i, "ts": ts, "amount": amt, "product": product, "channel": ch, "risk": 0.5, "addr1": addr1,
         "addr2": "87.0", "dist1": 0, "p_email": "gmail.com", "r_email": "", "m_flags": "", "c1": 1, "c13": 1,
         "d1": 0, "d15": 0, "model_score": ms, "@device": [dev] if dev else [], "@dev_status": [st] if st else [],
         "@proxy": [proxy] if proxy else []}
    return {"v_id": i, "v_type": "Txn", "attributes": a}


DEV_A, DEV_B = "SAMSUNG SM-G892A | Android 7.0 | chrome 62.0 | 1920x1080", "iOS Device | iOS 11.1 | safari 11.0 | 2436x1125"
CARD, CUST = "C08623-K2", "C08623"
ROW = {"case_id": "HHG-003", "opened_at": "2016-12-10 15:01:21", "trigger_type": "customer_report",
       "trigger_text": "Customer C08623 message: 'I never made this $49.00 purchase. Please check my card.' Refers to 3530164.",
       "flagged_txn_id": "3530164", "card_id": CARD, "customer_id": CUST, "risk_score": ""}
TXNS = [tx("3400001", "2016-11-01 10:00:00", 25.0, dev=DEV_B, st="Found"),
        tx("3400002", "2016-11-20 12:00:00", 31.5, dev=DEV_B, st="Found"),
        tx("3530100", "2016-12-10 09:00:00", 131.5, ms=0.8, dev=DEV_B, st="Found"),
        tx("3530164", "2016-12-10 11:30:00", 49.0, ms=0.9, dev=DEV_A, st="New")]
DEVICE = {"ever_txns": 9, "ever_cards": 3, "cards": [
    {"v_id": CARD, "v_type": "Card", "attributes": {"@n": 1, "@n_new": 1, "@amt": 49.0, "@first": "2016-12-10 11:30:00",
                                                   "@last": "2016-12-10 11:30:00", "@txns": ["3530164"], "@proxy": [],
                                                   "@cases": []}},
    {"v_id": "C00877-K1", "v_type": "Card", "attributes": {"@n": 2, "@n_new": 2, "@amt": 300.0, "@first": "2016-12-01 10:00:00",
                                                          "@last": "2016-12-02 10:00:00", "@txns": ["3500001", "3500002"],
                                                          "@proxy": ["IP_PROXY:ANONYMOUS"], "@cases": ["CC-0141", "CASE-HHG-004"]}}]}
CUSTOMER = {"cards": [{"v_id": CARD, "v_type": "Card", "attributes": {}},
                      {"v_id": "C08623-K1", "v_type": "Card", "attributes": {}}],
            "cases": [{"v_id": "CC-0200", "v_type": "ClosedCase",
                       "attributes": {"outcome": "cleared", "pattern": "none", "@cards": ["C08623-K1"]}}]}
RAG = {"context": "CASE\n...\nPOLICY & GUIDANCE\n- [POLICY-R2] R2 customer denies",
       "similar_cases": [{"id": "CC-0141", "type": "ClosedCase", "outcome_or_verdict": "confirmed_fraud",
                          "pattern": "card_not_present_new_device", "distance": 0.1},
                         {"id": "CASE-HHG-014", "type": "AgentCase", "outcome_or_verdict": "fraud",
                          "pattern": "undocumented", "distance": 0.2}],
       "docs": [{"id": "POLICY-R2", "title": "R2 customer denies the transaction", "distance": None},
                {"id": "PATTERN-card_not_present_new_device", "title": "Card-not-present fraud from a new device",
                 "distance": 0.2}],
       "calls": 2}
AMOUNTS = {v["v_id"]: v["attributes"]["amount"] for v in TXNS}


def assessment(**kw):
    a = {"episode": {"affected_txn_ids": ["3530100", "3530164"], "first_suspicious_txn_id": "3530100",
                     "exposure_usd": 180.5},
         "candidate_txn_ids": ["3530100", "3530164"], "signals": {"new_device": True}, "features": {"logit_flag": 2.2},
         "pattern": "card_not_present_new_device", "raw_pattern": "card_not_present_new_device",
         "pattern_reason": "online episode with a device marked New for this account",
         "prosecution": [{"claim": "Closed-case classifier scores flagged txn 3530164 at 0.90", "score": 0.9,
                          "entity_ids": ["3530164"], "ref": "model:closed_case_classifier"},
                         {"claim": "1 episode txn(s) came from a device marked New for this account", "score": 0.6,
                          "entity_ids": ["3530164"], "ref": "query:card_history(card_id=C08623-K2, window=60d)"}],
         "defence": [], "fraud_probability": 0.72, "model_probability": 0.72, "verdict": "uncertain",
         "independent_evidence": 2, "single_signal": False, "evidence_conflicts": False, "card_testing": False,
         "cleared_purchase_over_100": False, "recurring_match": False, "shared_origin": None,
         "connects_to_other_fraud": False, "connected_card_ids": [], "connected_device_profiles": []}
    a.update(kw)
    return a


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.queries, self.txns, self.customer = [], TXNS, CUSTOMER

        def fake_query(name, params):
            mcp_tools.calls += 1
            self.queries.append((name, params))
            if name == "card_history":
                self.assertLessEqual(params["t_to"], ROW["opened_at"])  # no look-ahead
                return {"txns": self.txns}
            if name == "customer_cases":
                return self.customer
            if name == "device_neighbors":
                return DEVICE
            if name == "region_cluster":
                return {"region_txns": 10, "region_cards": 4, "new_cards": []}
            raise AssertionError(name)

        self.upserts = []
        patches = [mock.patch.object(mcp_tools, "run_query", side_effect=fake_query),
                   mock.patch.object(mcp_tools, "upsert_case", side_effect=lambda v, e: self.upserts.append((v, e))),
                   mock.patch.object(mcp_tools, "upsert_case_embedding"),
                   mock.patch.object(llm, "embed", return_value=[[0.0] * 384]),
                   mock.patch.object(rag, "build_context", return_value=RAG)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_case(self, a, llm_reply=None, row=ROW, write=True):
        with mock.patch.object(analytics, "assess", return_value=a) as assess, \
             mock.patch.object(llm, "available", return_value=llm_reply is not None), \
             mock.patch.object(llm, "chat_json", side_effect=llm_reply) as chat:
            answer, trace = agent.investigate(row, write_graph=write)
        errs, _ = validate_answer(answer, AMOUNTS)
        self.assertEqual(errs, [], errs)
        self.assertEqual(answer["tool_calls"], len(self.queries))
        return answer, trace, assess, chat

    def test_legit_risk_score_no_request(self):
        row = {**ROW, "case_id": "HHG-001", "trigger_type": "risk_score", "risk_score": "0.61",
               "trigger_text": "Real-time model scored transaction 3530164 ($49.00, online) at 0.61."}
        a = assessment(episode={"affected_txn_ids": [], "first_suspicious_txn_id": "", "exposure_usd": 0.0},
                       pattern="none", pattern_reason="activity judged legitimate", fraud_probability=0.08,
                       verdict="legitimate", prosecution=[],
                       defence=[{"claim": "Classifier scores 3530164 at 0.08", "score": 0.92,
                                 "entity_ids": ["3530164"], "ref": "model:closed_case_classifier"},
                                {"claim": "Flagged device was used on this card before", "score": 0.5,
                                 "entity_ids": ["3530164"], "ref": "query:card_history"}])
        answer, trace, assess, _ = self.run_case(a, row=row)
        # flattened txn records reach analytics with the contract's keys, flagged device's neighbourhood as ctx
        txns = assess.call_args.args[0]
        self.assertEqual(set(txns[0]), {"id", *agent.TXN_KEYS, "device", "dev_status", "proxy"})
        self.assertEqual(txns[-1]["device"], DEV_A)
        self.assertEqual(assess.call_args.kwargs["device_ctx"]["cards"][1]["cases"], ["CC-0141"])  # later case hidden
        self.assertEqual(answer["evidence_requests"], [])
        nba = answer["next_best_actions"]
        self.assertEqual(nba["final"], nba["initial"])
        self.assertEqual(nba["what_changed"], "nothing")
        self.assertEqual([x["action"] for x in nba["final"]], ["CLOSE_NO_FRAUD"])
        self.assertEqual(answer["case"]["status"], "closed_legitimate")
        self.assertIsNone(trace["evidence_gate"])
        self.assertIn("§6", answer["stop_reason"])
        self.assertEqual(answer["sar"], {"file": False, "reason": answer["sar"]["reason"], "narrative": "",
                                         "subjects": [], "total_amount_usd": 0, "activity_dates": []})
        self.assertTrue(any(e["source"] == "document" and e["ref"] == "POLICY-R2" for e in answer["case"]["evidence"]))
        self.assertTrue(2 <= _sentences(answer["case"]["summary"]) <= 6)

    def test_customer_report_deny_blocks(self):
        def reply(system, user):
            if system is agent.PLANNER_SYSTEM:
                return {"calls": [{"option": "D1", "why": "other device on the card"}, {"option": "Z9"}],
                        "reasoning": "Check the cardholder's usual device for links."}
            return {"summary": "Card C99999-K1 was used. It is fraud.",  # invented id -> template
                    "what_changed": "The customer denied the charge (R2), so the card is blocked and a case opened.",
                    "pattern_description": "", "sar_narrative": "", "evidence_rewrites": ["too", "short"]}

        answer, trace, _, chat = self.run_case(assessment(), llm_reply=reply)
        self.assertEqual(chat.call_count, 2)
        devs = [p["device_id"] for n, p in self.queries if n == "device_neighbors"]
        self.assertEqual(devs, [DEV_A, DEV_B])  # planner's valid pick executed, invalid "Z9" dropped
        req = answer["evidence_requests"]
        self.assertEqual([(r["type"], r["asked_after_step"]) for r in req], [("customer_validation", 4)])
        self.assertIn("denies", req[0]["assumed_response"])
        nba = answer["next_best_actions"]
        self.assertEqual([x["action"] for x in nba["initial"]], ["VERIFY_WITH_CUSTOMER", "CREATE_CASE"])
        self.assertEqual([(x["action"], x["route"]) for x in nba["final"]], [("BLOCK_CARD", "L1"), ("CREATE_CASE", "auto")])
        self.assertTrue(nba["what_changed"].startswith("The customer denied"))
        c = answer["case"]
        self.assertEqual((c["status"], c["verdict"], c["fraud_probability"]), ("closed_fraud", "fraud", 0.9))
        self.assertNotIn("C99999", c["summary"])
        self.assertEqual(c["affected_txn_ids"], ["3530100", "3530164"])
        self.assertEqual(c["exposure_usd"], 180.5)
        self.assertEqual(c["similar_prior_cases"], ["CC-0141"])
        self.assertTrue(any(e["source"] == "customer" and e["ref"] == "evidence_request:1" for e in c["evidence"]))
        self.assertTrue(any(e["ref"] == "case_pack:trigger_text" for e in c["evidence"]))
        self.assertFalse(answer["sar"]["file"])
        self.assertEqual(trace["evidence_gate"]["type"], "customer_validation")
        self.assertEqual(trace["probability"], {"initial": 0.72, "final": 0.9, "features": {"logit_flag": 2.2}})
        self.assertEqual({s["step"] for s in trace["steps"]}, set(range(1, 9)))
        # case memory: AgentCase + edges to queried ids only
        (vertex, edges), = self.upserts
        self.assertEqual(vertex["id"], "CASE-HHG-003")
        self.assertEqual(sorted(edges), sorted([("INVOLVES", "3530100"), ("INVOLVES", "3530164"), ("ON_CARD", CARD),
                                                ("SIMILAR_TO", "CC-0141"), ("CITES", "POLICY-R2"),
                                                ("CITES", "PATTERN-card_not_present_new_device")]))
        self.assertEqual((c["written_to_graph"], c["graph_case_id"]), (True, "CASE-HHG-003"))

    def test_balanced_evidence_left_pending(self):
        a = assessment(fraud_probability=0.5)
        answer, trace, _, _ = self.run_case(a, write=False)
        (req,) = answer["evidence_requests"]
        self.assertTrue(req["assumed_response"].startswith("No response assumed yet"))
        self.assertEqual(answer["next_best_actions"]["final"], answer["next_best_actions"]["initial"])
        self.assertEqual(answer["case"]["verdict"], "uncertain")
        self.assertIsNone(trace["evidence_gate"]["assumed_response"])

    def test_customer_confirms_clears(self):
        a = assessment(fraud_probability=0.25, prosecution=[], defence=[
            {"claim": "Flagged device was used on this card before", "score": 0.5, "entity_ids": ["3530164"],
             "ref": "query:card_history"}])
        answer, _, _, _ = self.run_case(a, write=False)
        self.assertIn("confirms", answer["evidence_requests"][0]["assumed_response"])
        c = answer["case"]
        self.assertEqual((c["verdict"], c["affected_txn_ids"], c["exposure_usd"], c["pattern"]), ("legitimate", [], 0.0, "none"))
        # §3a: a disputed charge keeps its case; R3 closes it as legitimate
        self.assertEqual([x["action"] for x in answer["next_best_actions"]["final"]], ["CREATE_CASE", "CLOSE_NO_FRAUD"])
        self.assertEqual(answer["case"]["status"], "closed_legitimate")
        self.assertEqual((c["written_to_graph"], c["graph_case_id"]), (False, ""))
        self.assertEqual(self.upserts, [])

    def test_sar_block_ring(self):
        shared = {"kind": "device", "id": DEV_A, "card_ids": ["C00877-K1"]}
        a = assessment(fraud_probability=0.93, verdict="fraud", pattern="undocumented",
                       pattern_reason="device-profile ring: several other cards used the same rare device as New",
                       episode={"affected_txn_ids": ["3530100", "3530164"], "first_suspicious_txn_id": "3530100",
                                "exposure_usd": 180.5},
                       shared_origin=shared, connects_to_other_fraud=True, connected_card_ids=["C00877-K1"],
                       connected_device_profiles=[DEV_A])
        explain = {"summary": "Short.", "what_changed": "x", "pattern_description": "One sentence only.",
                   "sar_narrative": "Too short. Two sentences."}
        answer, trace, _, _ = self.run_case(a, llm_reply=lambda s, u: {"calls": []} if s is agent.PLANNER_SYSTEM else explain)
        final = [x["action"] for x in answer["next_best_actions"]["final"]]
        self.assertIn("FILE_REPORT", final)
        self.assertIn("MONITOR_CONNECTED_CARDS", final)
        self.assertEqual(answer["evidence_requests"], [])
        sar = answer["sar"]
        self.assertTrue(sar["file"])
        self.assertTrue(6 <= _sentences(sar["narrative"]) <= 12, sar["narrative"])  # template replaced the short one
        self.assertEqual(sar["subjects"], [CUST, CARD, "C00877-K1", DEV_A])
        self.assertEqual(sar["total_amount_usd"], answer["case"]["exposure_usd"])
        self.assertEqual(sar["activity_dates"], ["2016-12-10", "2016-12-10"])
        self.assertTrue(2 <= _sentences(answer["case"]["pattern_description"]) <= 3)
        self.assertEqual(answer["case"]["connected_card_ids"], ["C00877-K1"])
        (_, edges), = self.upserts
        self.assertIn(("CONNECTED_TO", "C00877-K1"), edges)
        self.assertIn(("LINKS_DEVICE", DEV_A), edges)
        flags = {n["id"]: n["flag"] for n in trace["graph"]["nodes"]}
        self.assertEqual((flags[CARD], flags["C00877-K1"], flags["3530164"]), ("subject", "suspicious", "suspicious"))

    def test_llm_text_naming_other_pattern_rejected(self):
        ok = "Card C08623-K2 was used from a new device. The customer denied txn 3530164, so the card is blocked."
        bad = "Card C08623-K2 shows an account takeover. The customer denied txn 3530164, so the card is blocked."
        for text, accepted in ((ok, True), (bad, False)):
            self.queries.clear()
            reply = lambda s, u, t=text: {"calls": []} if s is agent.PLANNER_SYSTEM else {"summary": t}  # noqa: E731
            answer, trace, _, _ = self.run_case(assessment(), llm_reply=reply, write=False)
            self.assertEqual(answer["case"]["pattern"], "card_not_present_new_device")
            self.assertEqual(answer["case"]["summary"] == text, accepted)
            fallback = next(s for s in trace["steps"] if s["name"] == "Explain decision")["args"]["fallback"]
            self.assertEqual("summary" in fallback, not accepted)

    def test_closed_case_txns_for_account_history(self):
        """Flag with an account key: txns of the card's closed cases opened in the 60-day window before opening
        are read with get_neighbors and handed to analytics as customer_ctx["case_txns"]."""
        self.txns = TXNS[:-1] + [dict(TXNS[-1], attributes={**TXNS[-1]["attributes"], "d1": 40})]
        case = lambda i, opened, card=CARD: {"v_id": i, "v_type": "ClosedCase", "attributes": {  # noqa: E731
            "outcome": "confirmed_fraud", "pattern": "account_takeover", "opened_at": opened, "@cards": [card]}}
        self.customer = {**CUSTOMER, "cases": [case("CC-0300", "2016-12-01 00:00:00"),
                                               case("CC-0301", "2016-09-01 00:00:00"),  # before the window
                                               case("CC-0302", "2016-12-11 00:00:00"),  # after opening
                                               case("CC-0303", "2016-12-02 00:00:00", "C08623-K1")]}  # other card

        def fake_call(tool, **args):
            mcp_tools.calls += 1
            self.queries.append((tool, args))
            return {"neighbors": [{"v_id": "3530100", "v_type": "Txn"}, {"v_id": "9999999", "v_type": "Txn"}]}

        with mock.patch.object(mcp_tools, "call", side_effect=fake_call):
            answer, trace, assess, _ = self.run_case(assessment(), write=False)
        reads = [args["vertex_id"] for tool, args in self.queries if tool == "get_neighbors"]
        self.assertEqual(reads, ["CC-0300"])
        ctx = assess.call_args.kwargs["customer_ctx"]
        self.assertEqual(ctx["case_txns"], {"3530100": ("CC-0300", "confirmed_fraud", "2016-12-01 00:00:00")})
        self.assertFalse(ctx["case_txns_partial"])
        self.assertTrue(any(s["tool"] == "tigergraph__get_neighbors" for s in trace["steps"]))

    def test_real_analytics_contract(self):
        """Flattened records go through the real analytics.assess without errors."""
        with mock.patch.object(llm, "available", return_value=False):
            answer, trace = agent.investigate(ROW, write_graph=False)
        self.assertEqual(validate_answer(answer, AMOUNTS)[0], [])
        self.assertIn("3530164", answer["case"]["affected_txn_ids"] or ["3530164"])


class LaterCaseIdsTest(unittest.TestCase):
    def test_case_pack_and_sentinel_cases_at_or_after_opening(self):
        import json
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from hhg import config
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "dataset").mkdir()
            (root / "dataset" / "case_pack.csv").write_text(
                "case_id,opened_at,trigger_type\nHHG-001,2016-12-01 00:00:00,risk_score\n"
                "HHG-002,2016-12-05 10:00:00,risk_score\nHHG-003,2016-12-09 00:00:00,risk_score\n", encoding="utf-8")
            traces = root / "sentinel_cases" / "traces"
            traces.mkdir(parents=True)
            for sid, ts in (("SEN-001", "2016-12-04 23:59:59"), ("SEN-002", "2016-12-06 00:00:00")):
                (traces / f"{sid}.json").write_text(json.dumps({"trigger": {"case_id": sid, "opened_at": ts}}))
            with mock.patch.object(config, "ROOT", root), mock.patch.object(config, "DATASET", root / "dataset"):
                ids = agent._later_case_ids(datetime(2016, 12, 5, 10, 0, 0))
        self.assertEqual(ids, {"CASE-HHG-002", "CASE-HHG-003", "CASE-SEN-002"})


if __name__ == "__main__":
    unittest.main()
