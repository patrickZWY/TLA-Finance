import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from safety.eval_matrix import MatrixConfig, build_backends, run_eval_matrix, write_matrix_report


ROOT = Path(__file__).resolve().parents[1]


class EvalMatrixTests(unittest.TestCase):
    def test_build_backends_includes_gold_local_and_skipped_paid(self):
        with patch.dict(os.environ, {}, clear=True):
            backends = build_backends(
                MatrixConfig(
                    cases_path=ROOT / "fixtures" / "semantic_codex_cases.json",
                    local_models=("qwen3:4b", "llama3.2:3b"),
                    paid_model="gpt-4o-mini",
                    include_gold=True,
                )
            )

        self.assertEqual([backend.name for backend in backends], [
            "gold",
            "local:qwen3:4b",
            "local:llama3.2:3b",
            "paid:gpt-4o-mini",
        ])
        self.assertEqual(backends[-1].skip_reason, "OPENAI_API_KEY is not set")

    def test_gold_only_matrix_writes_per_backend_and_combined_reports(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            report = run_eval_matrix(
                MatrixConfig(
                    cases_path=ROOT / "fixtures" / "semantic_codex_cases.json",
                    repo_root=ROOT,
                    output_dir=output_dir,
                    local_models=(),
                    include_gold=True,
                )
            )
            combined_path = write_matrix_report(report, output_dir / "model_eval_matrix.json")

            loaded = json.loads(combined_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["summary"]["status_counts"], {"passed": 1})
        self.assertEqual(loaded["backends"][0]["name"], "gold")
        self.assertEqual(loaded["backends"][0]["summary"]["total_cases"], 12)
        self.assertTrue(loaded["backends"][0]["summary"]["threshold_passed"])
        self.assertEqual(loaded["backends"][0]["summary"]["threshold_rates"]["pass_rate"], 1.0)
        self.assertEqual(loaded["config"]["thresholds"]["min_pass_rate"], 1.0)
        self.assertTrue(Path(loaded["backends"][0]["report_path"]).name.endswith(".json"))


if __name__ == "__main__":
    unittest.main()
