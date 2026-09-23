import json
import tempfile
import unittest
from pathlib import Path

from hhg import approvals


class ApprovalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "audit" / "approvals.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_sign_matrix(self):  # §2: team lead signs L1; fraud manager signs L1 and L2; nobody signs auto
        self.assertTrue(approvals.can_sign("L1", "L1"))
        self.assertFalse(approvals.can_sign("L1", "L2"))
        self.assertTrue(approvals.can_sign("L2", "L1"))
        self.assertTrue(approvals.can_sign("L2", "L2"))
        self.assertFalse(approvals.can_sign("L2", "auto"))

    def test_team_lead_cannot_sign_l2(self):
        with self.assertRaises(PermissionError):
            approvals.record("HHG-001", "FILE_REPORT", "L2", "approved", "L1", "ana", log=self.log)
        self.assertFalse(self.log.exists())

    def test_bad_decision(self):
        with self.assertRaises(ValueError):
            approvals.record("HHG-001", "BLOCK_CARD", "L1", "maybe", "L1", "ana", log=self.log)

    def test_append_only_history(self):
        approvals.record("HHG-001", "BLOCK_CARD", "L1", "approved", "L1", "ana", "ok",
                         [("customer_validation", "deny")], log=self.log)
        approvals.record("HHG-002", "DECLINE_TRANSACTION", "L1", "rejected", "L2", "raj", log=self.log)
        approvals.record("HHG-001", "BLOCK_CARD", "L1", "rejected", "L2", "raj", log=self.log)
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        h = approvals.history("HHG-001", log=self.log)
        self.assertEqual([e["decision"] for e in h], ["approved", "rejected"])
        self.assertEqual(h[0]["responses"], [["customer_validation", "deny"]])
        self.assertEqual(json.loads(lines[1])["case_id"], "HHG-002")
        self.assertEqual(approvals.history("HHG-003", log=self.log), [])


if __name__ == "__main__":
    unittest.main()
