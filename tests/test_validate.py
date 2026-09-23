import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hhg.validate import main, validate_answer

EXAMPLE = json.loads((Path(__file__).parent / "fixtures" / "example_HHG-017.json").read_text(encoding="utf-8"))
AMOUNTS = {"T0412877": 1.10, "T0412878": 2.40, "T0412879": 0.95, "T0412883": 263.98}


def errors(ans, **kw):
    return validate_answer(ans, **kw)[0]


def legit():
    a = copy.deepcopy(EXAMPLE)
    a["case"].update(verdict="legitimate", status="closed_legitimate", fraud_probability=0.05, pattern="none",
                     affected_txn_ids=[], first_suspicious_txn_id="", exposure_usd=0)
    close = [{"action": "CLOSE_NO_FRAUD", "route": "auto", "reason": "R3"}]
    a["next_best_actions"] = {"initial": close, "final": copy.deepcopy(close), "what_changed": "nothing"}
    a["evidence_requests"] = []
    a["sar"] = {"file": False, "reason": "§3a", "narrative": "", "subjects": [], "total_amount_usd": 0,
                "activity_dates": []}
    return a


class ValidateTest(unittest.TestCase):
    def test_readme_example_passes(self):
        errs, warns = validate_answer(EXAMPLE, amounts=AMOUNTS)
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)  # the README's MONITOR_CONNECTED_CARDS reason cites no rule

    def test_legit_template_passes(self):
        self.assertEqual(errors(legit()), [])

    def test_missing_field_and_bad_type(self):
        a = copy.deepcopy(EXAMPLE)
        del a["case"]["summary"]
        a["tokens"] = "12480"
        a["case"]["written_to_graph"] = 1
        errs = errors(a)
        self.assertTrue(any("case.summary: missing" in e for e in errs))
        self.assertTrue(any(".tokens: wrong type" in e for e in errs))
        self.assertTrue(any("written_to_graph: wrong type" in e for e in errs))

    def test_bad_enums(self):
        a = copy.deepcopy(EXAMPLE)
        a["case"]["pattern"] = "phishing"
        a["case"]["evidence"][0]["source"] = "guess"
        a["evidence_requests"][0]["type"] = "phone_call"
        a["next_best_actions"]["final"][1]["action"] = "FREEZE_ACCOUNT"
        self.assertEqual(len(errors(a)), 4)

    def test_route_must_match_exposure(self):
        a = copy.deepcopy(EXAMPLE)
        a["case"]["exposure_usd"] = 3000
        errs = errors(a)
        self.assertTrue(any("BLOCK_CARD route L1 != L2" in e for e in errs))

    def test_exposure_vs_amounts(self):
        self.assertTrue(any("exposure_usd" in e for e in errors(EXAMPLE, amounts=dict(AMOUNTS, T0412883=10.0))))
        self.assertTrue(any("no amount" in e for e in errors(EXAMPLE, amounts={})))

    def test_sar_must_match_final(self):
        a = copy.deepcopy(EXAMPLE)
        a["next_best_actions"]["final"] = [x for x in a["next_best_actions"]["final"] if x["action"] != "FILE_REPORT"]
        self.assertTrue(any("sar.file must agree" in e for e in errors(a)))

    def test_sar_false_requires_empty_fields(self):
        a = legit()
        a["sar"]["subjects"] = ["C00377"]
        self.assertTrue(any("sar.file false" in e for e in errors(a)))

    def test_sar_narrative_length_and_dates(self):
        a = copy.deepcopy(EXAMPLE)
        a["sar"]["narrative"] = "Too short. Two sentences."
        a["sar"]["activity_dates"] = ["2016-11-14"]
        errs = errors(a)
        self.assertTrue(any("sentences" in e for e in errs))
        self.assertTrue(any("activity_dates" in e for e in errs))

    def test_legitimate_rules(self):
        a = legit()
        a["case"]["exposure_usd"] = 5.0
        self.assertTrue(any("legitimate verdict" in e for e in errors(a)))

    def test_no_requests_means_no_change(self):
        a = legit()
        a["next_best_actions"]["what_changed"] = "customer confirmed"
        self.assertTrue(any("what_changed" in e for e in errors(a)))

    def test_pattern_description(self):
        a = copy.deepcopy(EXAMPLE)
        a["case"]["pattern"] = "undocumented"
        self.assertTrue(any("pattern_description" in e for e in errors(a)))

    def test_similar_case_ids_and_probability(self):
        a = copy.deepcopy(EXAMPLE)
        a["case"]["similar_prior_cases"] = ["CC-141"]
        a["case"]["fraud_probability"] = 1.2
        self.assertEqual(len(errors(a)), 2)

    def test_block_all_cards_needs_r10(self):
        a = copy.deepcopy(EXAMPLE)
        a["next_best_actions"]["final"][0] = {"action": "BLOCK_ALL_CARDS", "route": "L2", "reason": "R2"}
        self.assertTrue(any("R10" in e for e in errors(a)))
        a["next_best_actions"]["final"][0]["reason"] = "R10: two cards confirmed"
        self.assertEqual(errors(a), [])

    def test_known_ids(self):
        ids = {"T0412877", "T0412878", "T0412879", "T0412883", "C00877-K1", "CC-0141", "C00377", "C00377-K1"}
        self.assertEqual(errors(EXAMPLE, known_ids=ids), [])
        self.assertTrue(any("unknown ids" in e for e in errors(EXAMPLE, known_ids=ids - {"CC-0141"})))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "HHG-017.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([d]), 0)
            self.assertIn("1/1 files valid", out.getvalue())
            (Path(d) / "HHG-018.json").write_text("{}", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([d]), 1)


if __name__ == "__main__":
    unittest.main()
