import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "phase3b-corpus-v0.2.1"
EVIDENCE = ROOT / "benchmarks" / "phase4a-materializer-evidence"
SCRIPT = ROOT / "scripts" / "materialize_phase3b_mutants.py"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(canonical_json(value), encoding="utf-8")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebind_suite_manifest(evidence):
    manifest_path = evidence / "suite-manifest.json"
    manifest = read_json(manifest_path)
    manifest["artifacts"] = {
        path.relative_to(evidence).as_posix(): file_hash(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    write_json(manifest_path, manifest)


class Phase3bMutantMaterializerTests(unittest.TestCase):
    def setUp(self):
        self.corpus = read_json(CORPUS / "corpus.json")
        self.frozen_oracles = read_json(CORPUS / "mutant-results.json")
        self.results = read_json(EVIDENCE / "semantic-mutant-results.json")

    def validate(self, evidence):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--corpus",
                str(CORPUS),
                "--validate-existing",
                str(evidence),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_tamper_rejected(self, mutate):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            shutil.copytree(EVIDENCE, evidence)
            mutate(evidence)
            rebind_suite_manifest(evidence)
            completed = self.validate(evidence)
            self.assertNotEqual(
                completed.returncode,
                0,
                "coherently rehashed tamper was accepted",
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

    def test_all_oracles_are_observed_without_placeholders(self):
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

    def test_non_lower_cases_run_closed_oracle_before_artifacts(self):
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
            self.assertEqual(
                result["semantic_oracle"]["class"],
                "SemanticOracleViolation",
            )
            self.assertEqual(
                result["semantic_oracle"]["input_sha256"],
                result["mutated_projection_sha256"],
            )
            self.assertTrue(result["semantic_oracle"]["tool"]["sha256"])
            self.assertTrue(result["semantic_oracle"]["changed_paths"])

    def test_lower_inputs_have_total_mapping_and_exact_real_tlc_oracles(self):
        lower = {
            result["mutant_id"]: result
            for result in self.results["results"]
            if result["lowering_expectation"] == "lower"
        }
        self.assertEqual(
            set(lower),
            {
                "mutant.17.submitted-is-settled",
                "mutant.18.single-trace",
            },
        )
        expected_bases = {
            "mutant.17.submitted-is-settled": (
                "fixture.phase3a.lifecycle.ordered"
            ),
            "mutant.18.single-trace": (
                "fixture.phase3a.lifecycle.concurrent"
            ),
        }
        for mutant_id, result in lower.items():
            backend = result["backend"]
            proof = read_json(
                EVIDENCE / "lower" / mutant_id / "mapping-proof.json"
            )
            self.assertEqual(
                backend["input_derivation"],
                "projection_to_fsir_total_mapping",
            )
            self.assertEqual(
                proof["declared_mapping"]["base_fixture_id"],
                expected_bases[mutant_id],
            )
            self.assertEqual(
                proof["full_projection_binding"]["unchanged_projection_sha256"],
                proof["full_projection_binding"][
                    "mutated_projection_masked_sha256"
                ],
            )
            self.assertNotEqual(
                proof["mapped_baseline_input_sha256"],
                proof["mutated_input_sha256"],
            )
            fixture_hashes = {
                file_hash(
                    CORPUS
                    / "backend-artifacts"
                    / fixture
                    / "input.fsir.json"
                )
                for fixture in ("ordered", "concurrent")
            }
            self.assertNotIn(
                backend["input_fsir_sha256"], fixture_hashes
            )
            self.assertEqual(
                [item["path"] for item in proof["executable_delta"]],
                ["control.kind", "control.edges"],
            )
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

    def test_checked_in_evidence_recomputes_exactly(self):
        completed = self.validate(EVIDENCE)
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

    def test_registry_and_projection_proof_substitution_is_rejected(self):
        def mutate(evidence):
            path = evidence / "semantic-mutant-results.json"
            report = read_json(path)
            result = report["results"][0]
            result["semantic_gate_code"] = "substituted_gate"
            result["baseline_projection_sha256"] = "1" * 64
            result["mutated_projection_sha256"] = "2" * 64
            result["mutation_proof"][0]["path"] = "substituted.path"
            result["semantic_oracle"]["gate_code"] = "substituted_gate"
            write_json(path, report)

        self.assert_tamper_rejected(mutate)

    def test_canonical_fixture_substitution_is_rejected(self):
        def mutate(evidence):
            source = (
                CORPUS
                / "backend-artifacts"
                / "ordered"
                / "input.fsir.json"
            )
            target = (
                evidence
                / "lower"
                / "mutant.17.submitted-is-settled"
                / "input.fsir.json"
            )
            shutil.copyfile(source, target)

        self.assert_tamper_rejected(mutate)

    def test_backend_metadata_erasure_is_rejected(self):
        def mutate(evidence):
            path = evidence / "semantic-mutant-results.json"
            report = read_json(path)
            result = next(
                item
                for item in report["results"]
                if item["mutant_id"]
                == "mutant.17.submitted-is-settled"
            )
            result["backend"]["artifact_hashes"] = {}
            result["backend"].pop("execution_evidence_manifest")
            write_json(path, report)

        self.assert_tamper_rejected(mutate)

    def test_manifest_entry_and_artifact_deletion_is_rejected(self):
        def mutate(evidence):
            target = (
                evidence
                / "lower"
                / "mutant.17.submitted-is-settled"
                / "tlc-output.txt"
            )
            target.unlink()

        self.assert_tamper_rejected(mutate)

    def test_coherent_execution_report_rehash_is_rejected(self):
        def mutate(evidence):
            artifact_dir = (
                evidence / "lower" / "mutant.17.submitted-is-settled"
            )
            report_path = artifact_dir / "execution-report.json"
            execution_report = read_json(report_path)
            execution_report["returncode"] = 999
            execution_report["satisfied"] = False
            write_json(report_path, execution_report)

            execution_manifest_path = (
                artifact_dir / "execution-evidence-manifest.json"
            )
            execution_manifest = read_json(execution_manifest_path)
            execution_manifest["artifacts"]["execution_report"] = file_hash(
                report_path
            )
            write_json(execution_manifest_path, execution_manifest)

            results_path = evidence / "semantic-mutant-results.json"
            results = read_json(results_path)
            result = next(
                item
                for item in results["results"]
                if item["mutant_id"]
                == "mutant.17.submitted-is-settled"
            )
            result["backend"]["returncode"] = 999
            result["backend"]["execution_evidence_manifest"] = (
                execution_manifest
            )
            result["backend"]["artifact_hashes"][
                "execution-report.json"
            ] = file_hash(report_path)
            result["backend"]["artifact_hashes"][
                "execution-evidence-manifest.json"
            ] = file_hash(execution_manifest_path)
            result["semantic_oracle"]["returncode"] = 999
            write_json(results_path, results)

        self.assert_tamper_rejected(mutate)

    def test_placeholder_and_unexecuted_flags_are_rejected(self):
        def mutate(evidence):
            path = evidence / "semantic-mutant-results.json"
            report = read_json(path)
            result = report["results"][0]
            result["executed"] = False
            result["status"] = "oracle_defined_not_executed"
            result["mutated_projection_sha256"] = result[
                "baseline_projection_sha256"
            ]
            write_json(path, report)

        self.assert_tamper_rejected(mutate)


if __name__ == "__main__":
    unittest.main()
