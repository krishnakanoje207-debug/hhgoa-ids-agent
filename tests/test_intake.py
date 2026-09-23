import json
import tempfile
import unittest
from pathlib import Path

from hhg import intake, policy, replies

INFO = {"txn": {"id": "3450629", "ts": "2016-11-11 23:46:24", "amount": 100.09, "channel": "online",
                "addr1": "204.0", "risk": 0.57}, "card_id": "C04570-K1", "customer_id": "C04570"}


class MakeRowTest(unittest.TestCase):
    def test_risk_score_row_matches_case_pack_wording(self):
        r = intake.make_row("NEW-001", INFO, "risk_score")
        self.assertEqual(r["trigger_text"], "Real-time model scored transaction 3450629 ($100.09, online) at 0.57. "
                                            "Review and decide.")  # HHG-017's case-pack text
        self.assertEqual((r["opened_at"], r["card_id"], r["customer_id"], r["risk_score"]),
                         ("2016-11-12 00:46:24", "C04570-K1", "C04570", 0.57))

    def test_customer_report_default_message(self):
        r = intake.make_row("NEW-002", INFO, "customer_report")
        self.assertEqual(r["trigger_text"], "Customer C04570 message: 'I never made this $100.09 purchase. "
                                            "Please check my card.' Refers to 3450629.")

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            intake.make_row("NEW-003", INFO, "analyst_request")  # needs a message
        with self.assertRaises(ValueError):
            intake.make_row("NEW-003", INFO, "risk_score", opened_at="2016-11-10 00:00:00")  # before the txn
        with self.assertRaises(ValueError):
            intake.make_row("NEW-003", INFO, "rumour")

    def test_next_case_id(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(intake.next_case_id(Path(d)), "NEW-001")
            (Path(d) / "NEW-007.json").write_text("{}")
            self.assertEqual(intake.next_case_id(Path(d)), "NEW-008")


class RepliesTest(unittest.TestCase):
    TRACE = json.loads((Path(__file__).resolve().parents[1] / "cases" / "traces" / "HHG-017.json")
                       .read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "replies.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_until_the_cardholder_answers(self):  # HHG-017: balanced evidence, request left pending
        f, pending = replies.replay("HHG-017", self.TRACE, log=self.log)
        self.assertEqual(pending, "customer_validation")
        replies.record("HHG-017", "C04570", "deny", log=self.log)
        f, pending = replies.replay("HHG-017", self.TRACE, log=self.log)
        self.assertIsNone(pending)
        self.assertEqual([a["action"] for a in policy.decide(f)], ["BLOCK_CARD", "CREATE_CASE"])

    def test_portal_asks_instead_of_assuming(self):  # HHG-010: the agent assumed the customer confirms
        trace = json.loads((Path(__file__).resolve().parents[1] / "cases" / "traces" / "HHG-010.json")
                           .read_text(encoding="utf-8"))
        self.assertIsNone(replies.replay("HHG-010", trace, log=self.log)[1])
        self.assertEqual(replies.replay("HHG-010", trace, log=self.log, assume_customer=False)[1],
                         "customer_validation")

    def test_latest_wins_and_bad_answer(self):
        replies.record("HHG-017", "C04570", "deny", log=self.log)
        replies.record("HHG-017", "C04570", "confirm", log=self.log)
        self.assertEqual(replies.latest("HHG-017", log=self.log)["response"], "confirm")
        self.assertIsNone(replies.latest("HHG-001", log=self.log))
        with self.assertRaises(ValueError):
            replies.record("HHG-017", "C04570", "maybe", log=self.log)


if __name__ == "__main__":
    unittest.main()
