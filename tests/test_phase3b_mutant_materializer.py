import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "phase3b-corpus-v0.2.1"
EVIDENCE = ROOT / "benchmarks" / "phase4a-materializer-evidence"
SCRIPT = ROOT / "scripts" / "materialize_phase3b_mutants.py"


class Phase3bMutantMaterializerTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(
            (CORPUS / "corpus.json").read_text(encoding="utf-8")
        )
        self.frozen_oracles = json.loads(
            (CORPUS / "mutant-results.json").read_text(encoding="utf-8")
        )
        self.results = json.loads(
            (EVIDENCE / "semantic-mutant-results.json").read_text(
                encoding="utf-8"
            )
        )

    def test_frozen_corpus_remains_honest_and_materializer_is_separate(self):
        self.assertEqual(self.frozen_oracles["summary"]["executed"], 0)
        self.assertEqual(
            self.frozen_oracles["summary"]["status"],
            "oracle_complete_execution_pending_materializer",
        )
        self.assertEqual(self.results["summary"]["executed"], 32)
        self.assertEqual(self.results["summary"]["rejected_observed"], 32)
        self.assertEqual(self.results["summary"]["survivors"], 0)

    def test_all_oracles_are_executed_without_placeholders(self):
        expected = [
            mutant["id"]
            for case in self.corpus["cases"]
            for mutant in case["mutants"]
        ]
        observed = [result["mutant_id"] for result in self.results["results"]]
        self.assertEqual(observed, expected)
        self.assertEqual(len(observed), 32)
        for result in self.results["results"]:
            self.assertTrue(result["executed"])
            self.assertEqual(result["status"], "executed_rejected")
            self.assertFalse(result["survived"])
            self.assertNotEqual(
                result["baseline_projection_sha256"],
                result["mutated_projection_sha256"],
            )
            self.assertTrue(result["mutation_proof"])
            self.assertEqual(
                result["semantic_oracle"]["observed"], "rejected"
            )
            self.assertTrue(
                result["semantic_oracle"]["expected_gate_matched"]
            )
            self.assertTrue(
                result["semantic_oracle"]["frozen_contract_mismatch"]
            )

    def test_non_lower_cases_reject_before_artifacts(self):
        non_lower = [
            result
            for result in self.results["results"]
            if result["lowering_expectation"] != "lower"
        ]
        self.assertEqual(len(non_lower), 30)
        for result in non_lower:
            self.assertEqual(result["phase"], "pre_lowering_semantic_gate")
            self.assertFalse(result["artifacts_claimed"])
            self.assertIsNone(result["backend"])
            self.assertTrue(
                result["rejection"]["before_executable_artifacts"]
            )

    def test_lower_cases_have_exact_real_tlc_oracles(self):
        lower = {
            result["mutant_id"]: result
            for result in self.results["results"]
            if result["lowering_expectation"] == "lower"
        }
        self.assertEqual(set(lower), {
            "mutant.17.submitted-is-settled",
            "mutant.18.single-trace",
        })
        premature = lower["mutant.17.submitted-is-settled"]["backend"]
        self.assertEqual(premature["classification"], "property_violation")
        self.assertEqual(
            premature["property_ids"],
            [
                "property.safe_transfer_then_buy_order_sensitive."
                "no_negative_cash"
            ],
        )
        self.assertEqual(
            premature["event_ids"],
            ["event.buy.submit", "event.buy.execute"],
        )
        single = lower["mutant.18.single-trace"]["backend"]
        self.assertEqual(single["classification"], "passed")
        self.assertEqual(single["property_ids"], [])
        self.assertEqual(single["event_ids"], [])

    def test_checked_in_evidence_hashes_and_counts_validate(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--corpus",
                str(CORPUS),
                "--validate-existing",
                str(EVIDENCE),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "executed": 32,
                "rejected_observed": 32,
                "status": "pass",
                "survivors": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
