"""The UI's evidence replies start from trace["findings"]: replaying the agent's assumed replies through the
policy engine must reproduce every recorded answer's initial and final actions."""
import json
import unittest
from pathlib import Path

from hhg import policy

CASES = Path(__file__).resolve().parents[1] / "cases"


class ReplayTest(unittest.TestCase):
    def test_cases_replay(self):
        n = 0
        for p in sorted(CASES.glob("HHG-*.json")):
            trace = json.loads((CASES / "traces" / p.name).read_text(encoding="utf-8"))
            if "findings" not in trace:
                continue
            ans = json.loads(p.read_text(encoding="utf-8"))
            f = trace["findings"]
            with self.subTest(case=p.stem):
                self.assertEqual(policy.decide(f), ans["next_best_actions"]["initial"])
                for s in trace["steps"]:
                    if s["name"] == "Request more evidence" and s["args"].get("assumed_response"):
                        f = policy.apply_response(f, s["args"]["type"], s["args"]["assumed_response"])
                self.assertEqual(policy.decide(f), ans["next_best_actions"]["final"])
            n += 1
        if n == 0:
            self.skipTest("no trace has findings recorded")


if __name__ == "__main__":
    unittest.main()
