import unittest

from hhg import policy


def findings(**kw):
    f = {"trigger_type": "risk_score", "fraud_probability": 0.5, "verdict": "uncertain", "pattern": "none",
         "independent_evidence": 1, "single_signal": False, "evidence_conflicts": False, "exposure_usd": 100.0,
         "card_testing": False, "cleared_purchase_over_100": False, "shared_origin": None,
         "connects_to_other_fraud": False, "recurring_match": False, "customer_cards_confirmed_fraud": 0,
         "credentials_compromised": False, "customer_response": None, "step_up_result": None}
    f.update(kw)
    return f


def names(f):
    return [a["action"] for a in policy.decide(f)]


SHARED = {"kind": "device", "id": "SAMSUNG SM-G892A", "card_ids": ["C00877-K1", "C00990-K1"]}


class RouteTest(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(policy.route("BLOCK_CARD", 2500), "L1")
        self.assertEqual(policy.route("BLOCK_CARD", 2500.01), "L2")
        self.assertEqual(policy.route("DECLINE_TRANSACTION", 99999), "L1")
        self.assertEqual(policy.route("FILE_REPORT", 1), "L2")
        self.assertEqual(policy.route("BLOCK_ALL_CARDS", 1), "L2")
        self.assertEqual(policy.route("VERIFY_WITH_CUSTOMER", 99999), "auto")


class DecideTest(unittest.TestCase):
    def test_readme_3b_example(self):
        f = findings(fraud_probability=0.45, single_signal=True, exposure_usd=300.0)
        initial = names(f)
        self.assertEqual(initial[0], "VERIFY_WITH_CUSTOMER")
        self.assertNotIn("BLOCK_CARD", initial)
        self.assertIn("CREATE_CASE", initial)  # §3a: p >= 0.30 and evidence requested
        gate = policy.evidence_gate(f)
        self.assertEqual(gate["type"], "customer_validation")
        self.assertIn("BLOCK_CARD", gate["outcomes"]["deny"])
        # customer denies -> probability rises; R2 (report because of shared device), connected cards monitored
        final = names(dict(f, customer_response="deny", fraud_probability=0.86, verdict="fraud",
                           shared_origin=SHARED, independent_evidence=3))
        self.assertEqual(final, ["BLOCK_CARD", "CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"])
        # without a connection or large exposure: case only, no report
        final = names(dict(f, customer_response="deny", fraud_probability=0.86, verdict="fraud"))
        self.assertEqual(final, ["BLOCK_CARD", "CREATE_CASE"])

    def test_every_reason_cites_rule(self):
        cases = [findings(), findings(verdict="legitimate", fraud_probability=0.05),
                 findings(customer_response="confirm"), findings(customer_response="no_reply", exposure_usd=900),
                 findings(card_testing=True, cleared_purchase_over_100=True, fraud_probability=0.9, verdict="fraud"),
                 findings(pattern="undocumented", connects_to_other_fraud=True)]
        for f in cases:
            for a in policy.decide(f):
                self.assertRegex(a["reason"], r"R\d+|§")
                self.assertEqual(a["route"], policy.route(a["action"], f["exposure_usd"]))

    def test_r3_confirm_closes(self):
        self.assertEqual(names(findings(customer_response="confirm", verdict="legitimate")),
                         ["CREATE_CASE", "CLOSE_NO_FRAUD"])

    def test_legitimate_low_probability_closes_without_case(self):
        self.assertEqual(names(findings(verdict="legitimate", fraud_probability=0.05)), ["CLOSE_NO_FRAUD"])

    def test_r1_never_blocks_on_single_weak_signal(self):
        acts = names(findings(single_signal=True, fraud_probability=0.65, verdict="fraud", exposure_usd=3000))
        self.assertIn("VERIFY_WITH_CUSTOMER", acts)
        self.assertFalse({"BLOCK_CARD", "BLOCK_ALL_CARDS"} & set(acts))

    def test_r2_report_over_1000(self):
        acts = policy.decide(findings(customer_response="deny", verdict="fraud", fraud_probability=0.9,
                                      exposure_usd=3000))
        self.assertEqual([a["action"] for a in acts], ["BLOCK_CARD", "CREATE_CASE", "FILE_REPORT"])
        self.assertEqual(acts[0]["route"], "L2")

    def test_r4_no_reply(self):
        self.assertEqual(names(findings(customer_response="no_reply", exposure_usd=200)),
                         ["DECLINE_TRANSACTION", "MONITOR_CARD", "CREATE_CASE"])
        self.assertIn("ESCALATE_TO_ANALYST", names(findings(customer_response="no_reply", exposure_usd=600)))

    def test_r5_card_testing(self):
        f = findings(card_testing=True, verdict="fraud", fraud_probability=0.8, independent_evidence=2)
        self.assertEqual(names(f)[:2], ["DECLINE_TRANSACTION", "STEP_UP_AUTH"])
        self.assertNotIn("BLOCK_CARD", names(f))
        self.assertIn("BLOCK_CARD", names(dict(f, cleared_purchase_over_100=True)))

    def test_r6_shared_origin(self):
        acts = names(findings(shared_origin=SHARED, verdict="fraud", fraud_probability=0.9, independent_evidence=3))
        for a in ("CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"):
            self.assertIn(a, acts)
        mcc = next(a for a in policy.decide(findings(shared_origin=SHARED)) if a["action"] == "MONITOR_CONNECTED_CARDS")
        self.assertIn("C00990-K1", mcc["reason"])

    def test_r7_recurring_dispute(self):
        acts = names(findings(trigger_type="customer_report", recurring_match=True, verdict="legitimate",
                              fraud_probability=0.1))
        self.assertEqual(set(acts), {"CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"})

    def test_r8_uncertain_exposed(self):
        self.assertIn("ESCALATE_TO_ANALYST", names(findings(exposure_usd=800)))
        self.assertNotIn("ESCALATE_TO_ANALYST", names(findings(exposure_usd=400)))
        self.assertIn("ESCALATE_TO_ANALYST", names(findings(evidence_conflicts=True, verdict="fraud")))

    def test_r9_undocumented_coordinated(self):
        acts = names(findings(pattern="undocumented", connects_to_other_fraud=True))
        for a in ("CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"):
            self.assertIn(a, acts)

    def test_r10(self):
        f = findings(customer_response="deny", verdict="fraud", fraud_probability=0.9)
        self.assertNotIn("BLOCK_ALL_CARDS", names(dict(f, customer_cards_confirmed_fraud=1)))
        acts = policy.decide(dict(f, customer_cards_confirmed_fraud=2))
        self.assertIn("R10", next(a["reason"] for a in acts if a["action"] == "BLOCK_ALL_CARDS"))
        self.assertIn("BLOCK_ALL_CARDS", names(dict(f, credentials_compromised=True)))

    def test_order_is_deterministic(self):
        f = findings(shared_origin=SHARED, customer_response="deny", verdict="fraud")
        self.assertEqual(policy.decide(f), policy.decide(dict(f)))
        order = [policy.ORDER.index(a) for a in names(f)]
        self.assertEqual(order, sorted(order))


class CaseSarTest(unittest.TestCase):
    def test_needs_case(self):
        self.assertTrue(policy.needs_case(findings(fraud_probability=0.30)))
        self.assertTrue(policy.needs_case(findings(fraud_probability=0.1, trigger_type="customer_report")))
        self.assertTrue(policy.needs_case(findings(fraud_probability=0.1, step_up_result="pass")))
        self.assertFalse(policy.needs_case(findings(fraud_probability=0.29)))

    def test_needs_sar_agrees_with_actions(self):
        for f in (findings(customer_response="deny", exposure_usd=5000), findings(customer_response="deny"),
                  findings(customer_response="confirm")):
            acts = policy.decide(f)
            file, reason = policy.needs_sar(f, acts)
            self.assertEqual(file, "FILE_REPORT" in [a["action"] for a in acts])
            self.assertRegex(reason, r"R\d+|§")


class StopGateTest(unittest.TestCase):
    def test_stop_on_decisive_probability(self):
        stop, reason = policy.should_stop(findings(verdict="fraud", fraud_probability=0.9, independent_evidence=2))
        self.assertTrue(stop)
        self.assertIn("§6", reason)

    def test_stop_on_verification(self):
        self.assertTrue(policy.should_stop(findings(customer_response="deny"))[0])

    def test_continue_when_request_can_flip(self):
        stop, _ = policy.should_stop(findings(single_signal=True, fraud_probability=0.45))
        self.assertFalse(stop)

    def test_gate_none_when_nothing_to_ask(self):
        f = findings(verdict="legitimate", fraud_probability=0.2, independent_evidence=1)
        self.assertIsNone(policy.evidence_gate(f))
        self.assertTrue(policy.should_stop(f)[0])

    def test_gate_prefers_cheapest(self):
        # conflicting evidence: analyst_info is cheaper than asking the customer
        gate = policy.evidence_gate(findings(evidence_conflicts=True, single_signal=True, fraud_probability=0.5))
        self.assertEqual(gate["type"], "analyst_info")
        # card testing recommends STEP_UP_AUTH, so step_up_auth is requested
        gate = policy.evidence_gate(findings(card_testing=True, verdict="fraud", fraud_probability=0.8))
        self.assertEqual(gate["type"], "step_up_auth")
        self.assertIn("BLOCK_CARD", gate["outcomes"]["fail"])

    def test_status_for(self):
        f = findings()
        s = lambda **kw: policy.status_for(f, policy.decide(findings(**kw)))
        self.assertEqual(s(customer_response="confirm"), "closed_legitimate")
        self.assertEqual(s(customer_response="deny"), "closed_fraud")
        self.assertEqual(s(customer_response="no_reply", exposure_usd=900), "escalated")
        self.assertEqual(s(customer_response="no_reply"), "open")


if __name__ == "__main__":
    unittest.main()
