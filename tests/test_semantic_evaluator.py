import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from safety.evaluator import (
    SemanticEvalConfig,
    SemanticEvalThresholds,
    evaluate_thresholds,
    run_semantic_eval,
    write_eval_report,
)


ROOT = Path(__file__).resolve().parents[1]


class SemanticEvaluatorTests(unittest.TestCase):
    def test_gold_semantic_eval_matches_labeled_cases(self):
        report = run_semantic_eval(
            SemanticEvalConfig(
                cases_path=ROOT / "fixtures" / "semantic_codex_cases.json",
                repo_root=ROOT,
                transformer="gold",
            )
        )

        summary = report["summary"]
        self.assertTrue(summary["all_cases_passed"])
        self.assertEqual(summary["total_cases"], 12)
        self.assertEqual(summary["schema_valid_cases"], 12)
        self.assertEqual(summary["exact_action_matches"], 12)
        self.assertEqual(summary["finding_code_matches"], 12)
        self.assertEqual(summary["by_category"]["safe"]["total_cases"], 5)
        self.assertEqual(summary["by_category"]["unsafe"]["total_cases"], 5)
        self.assertEqual(summary["by_category"]["adversarial"]["total_cases"], 2)
        self.assertIn("budget_exceeded", summary["by_risk_type"])
        self.assertEqual(report["cases"][0]["actual_actions"], report["cases"][0]["expected_actions"])
        self.assertEqual(report["cases"][0]["category"], "safe")

    def test_eval_report_can_be_written_as_json(self):
        report = run_semantic_eval(
            SemanticEvalConfig(
                cases_path=ROOT / "fixtures" / "semantic_codex_cases.json",
                repo_root=ROOT,
                transformer="gold",
            )
        )
        with TemporaryDirectory() as tmpdir:
            path = write_eval_report(report, Path(tmpdir) / "report.json")
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["summary"]["total_cases"], 12)
        self.assertIn("by_category", loaded["summary"])

    def test_threshold_report_flags_rates_below_gate(self):
        summary = {
            "total_cases": 12,
            "passed_cases": 11,
            "schema_valid_cases": 12,
            "exact_action_matches": 11,
            "finding_code_matches": 12,
        }

        report = evaluate_thresholds(
            summary,
            SemanticEvalThresholds(min_pass_rate=1.0, min_exact_action_rate=1.0),
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["rates"]["pass_rate"], 0.9167)
        self.assertEqual(len(report["failures"]), 2)

    def test_threshold_report_passes_when_rates_meet_gate(self):
        summary = {
            "total_cases": 12,
            "passed_cases": 11,
            "schema_valid_cases": 12,
            "exact_action_matches": 11,
            "finding_code_matches": 12,
        }

        report = evaluate_thresholds(
            summary,
            SemanticEvalThresholds(min_pass_rate=0.9, min_exact_action_rate=0.9),
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main()
