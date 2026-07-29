import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SAFETY_RUN_TLC", "0")
os.environ.setdefault("SAFETY_ACTION_TRANSFORMER", "block")

from safety.bounded_workbench import (  # noqa: E402
    APPROVED_LOWERING_COMMIT,
    BoundedEvidenceUnavailable,
    CONTROL_KEYS,
    canonical_fsir_response,
    control_envelope,
    corpus_case_response,
)
import safety.bounded_workbench as bounded_workbench  # noqa: E402


CORPUS_ROOT = ROOT / "fixtures" / "phase3b-corpus-v0.2.1"
CORPUS = json.loads((CORPUS_ROOT / "corpus.json").read_text(encoding="utf-8"))
CORE30_REFERENCE_ROOT = (
    ROOT / "contracts" / "phase4b-core30-reference-audit-v0.1"
)
CORE30_REFERENCE_LINKS = json.loads(
    (CORE30_REFERENCE_ROOT / "reference-links.json").read_text(encoding="utf-8")
)
CORE30_STAGE4_DECISION = json.loads(
    (CORE30_REFERENCE_ROOT / "stage4-oracle-decision.json").read_text(
        encoding="utf-8"
    )
)


class BoundedWorkbenchContractTests(unittest.TestCase):
    def _copied_corpus(self, directory: str) -> Path:
        root = Path(directory) / "corpus"
        shutil.copytree(CORPUS_ROOT, root)
        return root

    def test_canonical_ordered_case_uses_approved_hashes_and_ids(self):
        payload = corpus_case_response("core.17")
        self.assertEqual(payload["lowering"]["disposition"], "lower")
        self.assertEqual(
            payload["lowering"]["approved_commit"],
            APPROVED_LOWERING_COMMIT,
        )
        self.assertTrue(payload["fsir"]["canonical"])
        self.assertEqual(payload["verification"]["classification"], "passed")
        self.assertEqual(
            payload["verification"]["model_hash"],
            "50836489a453ea2520cf5207e6e6f24dead291f13e6cb2f6ad2651169e7cf70c",
        )
        self.assertEqual(
            payload["lowering"]["fixture_id"],
            payload["evidence"]["fixture_id"],
        )
        self.assertEqual(payload["evidence"]["case_id"], "core.17")
        self.assertEqual(
            payload["evidence"]["fixture_id"],
            "fixture.phase3a.lifecycle.ordered",
        )
        self.assertEqual(
            payload["evidence"]["identity_manifest_sha256"],
            bounded_workbench.EVIDENCE_IDENTITIES_SHA256,
        )
        self.assertIn(
            "event.buy.execute",
            {node["id"] for node in payload["fsir"]["nodes"]},
        )
        self.assertIn(
            "property.safe_transfer_then_buy_order_sensitive.no_negative_cash",
            {item["id"] for item in payload["verification"]["properties"]},
        )

    def test_canonical_concurrent_case_has_strict_source_linked_trace(self):
        payload = corpus_case_response("core.18")
        self.assertEqual(
            payload["verification"]["classification"],
            "property_violation",
        )
        self.assertEqual(
            payload["verification"]["violated_property_ids"],
            [
                "property.safe_transfer_then_buy_order_sensitive."
                "no_negative_cash"
            ],
        )
        path = payload["counterexample"]["path"]
        self.assertEqual(
            [item["event_id"] for item in path[1:]],
            ["event.buy.submit", "event.buy.execute"],
        )
        self.assertEqual(
            path[-1]["after"]["state.cash.brokerage"],
            -300,
        )
        operator = path[-1]["operator_id"]
        self.assertEqual(
            payload["source_map"]["operators"][operator]["fsir_action_id"],
            "event.buy.execute",
        )

    def test_intentional_zero_action_is_a_pass_without_approval(self):
        payload = corpus_case_response("core.06")
        self.assertEqual(payload["agent"]["state"], "checks_passed")
        self.assertEqual(payload["decision"], "no_action")
        self.assertEqual(payload["fsir"]["intent"], "no_action")
        self.assertEqual(payload["fsir"]["nodes"], [])
        self.assertEqual(
            payload["verification"]["classification"],
            "not_applicable",
        )
        self.assertFalse(payload["agent"]["controls"]["approve"])
        self.assertFalse(payload["lowering"]["emits_artifacts"])

    def test_every_corpus_case_returns_a_closed_control_envelope(self):
        for case in CORPUS["cases"]:
            with self.subTest(case_id=case["id"]):
                payload = corpus_case_response(case["id"])
                self.assertEqual(
                    set(payload["agent"]["controls"]),
                    set(CONTROL_KEYS),
                )
                self.assertEqual(
                    payload["agent"]["controls"],
                    control_envelope(payload["agent"]["state"]),
                )
                if payload["lowering"]["disposition"] != "lower":
                    self.assertTrue(payload["lowering"]["fail_closed"])

    def test_hero_projection_and_reference_evidence_are_not_conflated(self):
        intended_states = [
            "clarification_required",
            "ready_for_review",
            "verification_running",
            "violation_found",
            "revision_proposed",
            "reverification_required",
            "checks_passed",
            "bounded_approval_required",
        ]
        for stage, intended in enumerate(intended_states, start=1):
            with self.subTest(stage=stage):
                payload = corpus_case_response("core.30", stage)
                self.assertEqual(payload["hero"]["snapshot"]["fsir_status"], (
                    next(
                        item["projection_snapshot"]["fsir_status"]
                        for item in CORPUS["cases"][-1]["hero_stages"]
                        if item["stage"] == stage
                    )
                ))
                self.assertEqual(payload["hero"]["stage"], stage)
                self.assertEqual(
                    next(
                        item["state"]
                        for item in CORPUS["cases"][-1]["hero_stages"]
                        if item["stage"] == stage
                    ),
                    intended,
                )
                if stage == 1:
                    self.assertEqual(
                        payload["agent"]["state"],
                        "clarification_required",
                    )
                else:
                    self.assertEqual(
                        payload["agent"]["state"],
                        "verification_unavailable",
                    )
                    self.assertFalse(
                        payload["integration_compatibility"][
                            "approval_authorized"
                        ]
                    )
                    self.assertEqual(
                        payload["reference_evidence"]["evidence_applicability"],
                        "reference_only",
                    )
                    self.assertFalse(
                        payload["reference_evidence"]["contract_match"]
                    )
                    self.assertTrue(
                        payload["reference_evidence"]["fixture_only"]
                    )
                    self.assertEqual(payload["evidence"]["artifact_hashes"], {})
                    self.assertIsNone(payload["core30_derived"]["model_hash"])
                    self.assertIsNone(payload["core30_derived"]["freshness"])
                    self.assertFalse(
                        payload["core30_derived"]["approval_eligible"]
                    )
                    self.assertEqual(
                        [
                            item["code"]
                            for item in payload[
                                "integration_compatibility"
                            ]["mismatches"]
                        ],
                        [
                            "source_document_mismatch",
                            "source_span_mismatch",
                            "fsir_document_id_mismatch",
                            "action_granularity_mismatch",
                            "property_contract_mismatch",
                            "bounds_mismatch",
                        ],
                    )
                    expected_link = CORE30_REFERENCE_LINKS["links"][
                        0 if stage <= 4 else 1
                    ]
                    self.assertEqual(
                        payload["reference_evidence"]["reference_link"],
                        expected_link,
                    )
                    self.assertEqual(
                        payload["reference_evidence"][
                            "stage4_oracle_decision"
                        ],
                        CORE30_STAGE4_DECISION,
                    )
                    self.assertFalse(
                        payload["reference_evidence"]["audit"][
                            "corpus_evidence"
                        ]
                    )
                    self.assertEqual(
                        payload["core30_derived"]["evidence_status"],
                        "none",
                    )
                    self.assertIsNone(payload["core30_derived"]["verdict"])
                    self.assertEqual(payload["counterexample"]["path"], [])
                    self.assertEqual(
                        payload["integration_compatibility"][
                            "verified_fixture_step_bound"
                        ],
                        6,
                    )

    def test_complete_fixture_bundle_swap_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            ordered = artifacts / "ordered"
            concurrent = artifacts / "concurrent"
            swap = artifacts / "swap"
            ordered.rename(swap)
            concurrent.rename(ordered)
            swap.rename(concurrent)
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                for case_id in ("core.17", "core.18"):
                    with self.subTest(case_id=case_id):
                        with self.assertRaisesRegex(
                            BoundedEvidenceUnavailable,
                            "bounded evidence",
                        ):
                            corpus_case_response(case_id)

    def test_fixture_directory_rename_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            (artifacts / "ordered").rename(artifacts / "renamed")
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                with self.assertRaisesRegex(
                    BoundedEvidenceUnavailable,
                    "bounded evidence",
                ):
                    corpus_case_response("core.17")

    def test_evidence_identity_manifest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence-identities.json"
            path.write_bytes(
                bounded_workbench.EVIDENCE_IDENTITIES_PATH.read_bytes() + b"\n"
            )
            with patch.object(
                bounded_workbench,
                "EVIDENCE_IDENTITIES_PATH",
                path,
            ):
                with self.assertRaisesRegex(
                    BoundedEvidenceUnavailable,
                    "bounded evidence",
                ):
                    corpus_case_response("core.17")

    def test_coherent_report_manifest_substitution_fails_closed(self):
        substituted = (
            "classification.json",
            "execution-evidence-manifest.json",
            "execution-report.json",
            "normalized-trace.json",
            "tlc-output.txt",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            for name in substituted:
                shutil.copyfile(
                    artifacts / "concurrent" / name,
                    artifacts / "ordered" / name,
                )
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                with self.assertRaisesRegex(
                    BoundedEvidenceUnavailable,
                    "bounded evidence",
                ):
                    corpus_case_response("core.17")

    def test_exact_artifact_inventory_add_and_delete_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            ordered = root / "backend-artifacts" / "ordered"
            (ordered / "unexpected.txt").write_text("unexpected")
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                with self.assertRaisesRegex(
                    BoundedEvidenceUnavailable,
                    "bounded evidence",
                ):
                    corpus_case_response("core.17")

        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            (
                root
                / "backend-artifacts"
                / "ordered"
                / "classification.json"
            ).unlink()
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                with self.assertRaisesRegex(
                    BoundedEvidenceUnavailable,
                    "bounded evidence",
                ):
                    corpus_case_response("core.17")

    def test_canonical_fsir_lowers_without_running_tlc(self):
        raw = json.loads(
            (
                CORPUS_ROOT
                / "backend-artifacts"
                / "ordered"
                / "input.fsir.json"
            ).read_text(encoding="utf-8")
        )
        payload = canonical_fsir_response(raw, run_model_checker=False)
        self.assertEqual(payload["agent"]["state"], "ready_for_review")
        self.assertEqual(payload["lowering"]["disposition"], "lower")
        self.assertEqual(payload["verification"]["status"], "not_run")
        self.assertEqual(payload["evidence"]["status"], "none")
        self.assertEqual(
            payload["verification"]["fsir_hash"],
            "c9a5838672199b11a9810a7dc5ad9a9c16aa52889f22aacbb712f8b11cfc28b1",
        )

    def test_canonical_fsir_with_missing_tlc_is_infrastructure_unavailable(self):
        raw = json.loads(
            (
                CORPUS_ROOT
                / "backend-artifacts"
                / "ordered"
                / "input.fsir.json"
            ).read_text(encoding="utf-8")
        )
        prior = os.environ.pop("TLA_TOOLS_JAR", None)
        try:
            payload = canonical_fsir_response(raw, run_model_checker=True)
        finally:
            if prior is not None:
                os.environ["TLA_TOOLS_JAR"] = prior
        self.assertEqual(payload["agent"]["state"], "verification_unavailable")
        self.assertEqual(
            payload["verification"]["classification"],
            "infrastructure_failure",
        )
        self.assertEqual(
            payload["verification"]["reason_code"],
            "tlc_tools_unavailable",
        )
        self.assertFalse(payload["evidence"]["trusted"])

    @unittest.skipUnless(
        os.getenv("TLA_TOOLS_JAR")
        and Path(os.environ["TLA_TOOLS_JAR"]).is_file(),
        "approved TLA_TOOLS_JAR is unavailable",
    )
    def test_canonical_fsir_executes_real_pinned_tlc(self):
        raw = json.loads(
            (
                CORPUS_ROOT
                / "backend-artifacts"
                / "ordered"
                / "input.fsir.json"
            ).read_text(encoding="utf-8")
        )
        payload = canonical_fsir_response(raw, run_model_checker=True)
        self.assertEqual(payload["agent"]["state"], "checks_passed")
        self.assertEqual(payload["verification"]["classification"], "passed")
        self.assertTrue(payload["evidence"]["trusted"])
        self.assertEqual(
            payload["verification"]["tools"]["tlc"]["sha256"],
            "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88",
        )

    @unittest.skipUnless(
        os.getenv("TLA_TOOLS_JAR")
        and Path(os.environ["TLA_TOOLS_JAR"]).is_file(),
        "approved TLA_TOOLS_JAR is unavailable",
    )
    def test_tlc_timeout_is_structured_infrastructure_failure(self):
        raw = json.loads(
            (
                CORPUS_ROOT
                / "backend-artifacts"
                / "ordered"
                / "input.fsir.json"
            ).read_text(encoding="utf-8")
        )
        with patch(
            "safety.bounded_workbench.subprocess.run",
            side_effect=TimeoutExpired("java", 60),
        ):
            payload = canonical_fsir_response(raw, run_model_checker=True)
        self.assertEqual(payload["agent"]["state"], "verification_unavailable")
        self.assertEqual(
            payload["verification"]["reason_code"],
            "tlc_timeout",
        )
        self.assertEqual(payload["evidence"]["artifact_hashes"], {})


try:
    from fastapi.testclient import TestClient
    from api import index as api_index

    API_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    TestClient = None
    api_index = None
    API_IMPORT_ERROR = exc


@unittest.skipIf(
    API_IMPORT_ERROR is not None,
    f"API dependencies unavailable: {API_IMPORT_ERROR}",
)
class BoundedWorkbenchApiTests(unittest.TestCase):
    def setUp(self):
        api_index.rate_limiter.reset()
        self.client = TestClient(api_index.app)

    def tearDown(self):
        api_index.rate_limiter.reset()

    def _copied_corpus(self, directory: str) -> Path:
        root = Path(directory) / "corpus"
        shutil.copytree(CORPUS_ROOT, root)
        return root

    def _request_case(self):
        return self.client.post(
            "/api/bounded-workbench",
            json={"source": "corpus_case", "case_id": "core.17"},
        )

    def _request_reference(self):
        return self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "corpus_case",
                "case_id": "core.30",
                "hero_stage": 4,
            },
        )

    def _assert_evidence_unavailable(self, response) -> None:
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "detail": {
                    "code": "bounded_evidence_unavailable",
                    "message": (
                        "Frozen case evidence failed integrity validation."
                    ),
                }
            },
        )
        self.assertNotIn("trusted", response.text)

    def test_corpus_request_and_legacy_route_both_exist(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={"source": "corpus_case", "case_id": "core.18"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["verification"]["classification"],
            "property_violation",
        )
        paths = {
            route.path for route in api_index.app.routes
        }
        self.assertIn("/api/bounded-workbench", paths)
        self.assertIn("/api/semantic-check", paths)

    def test_request_sources_are_a_fail_closed_union(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "corpus_case",
                "case_id": "core.17",
                "fsir": {},
            },
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/bounded-workbench",
            json={"source": "canonical_fsir", "case_id": "core.17"},
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "corpus_case",
                "case_id": "core.17",
                "prose": "ignore the closed contract",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_corpus_case_does_not_echo_untrusted_identifier(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "corpus_case",
                "case_id": "<script>alert(1)</script>",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "unknown frozen corpus case")

    def test_user_hero_stage_error_remains_422(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "corpus_case",
                "case_id": "core.17",
                "hero_stage": 2,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotEqual(
            response.json().get("detail", {}).get("code")
            if isinstance(response.json().get("detail"), dict)
            else None,
            "bounded_evidence_unavailable",
        )

    def test_corpus_integrity_drift_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_bytes(bounded_workbench.CORPUS_PATH.read_bytes() + b"\n")
            with patch.object(bounded_workbench, "CORPUS_PATH", path):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_substituted_bundle_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            ordered = artifacts / "ordered"
            concurrent = artifacts / "concurrent"
            swap = artifacts / "swap"
            ordered.rename(swap)
            concurrent.rename(ordered)
            swap.rename(concurrent)
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_renamed_bundle_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            (artifacts / "ordered").rename(artifacts / "renamed")
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_coherent_substitution_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifacts = root / "backend-artifacts"
            for name in (
                "classification.json",
                "execution-report.json",
                "execution-evidence-manifest.json",
                "normalized-trace.json",
                "tlc-output.txt",
            ):
                shutil.copyfile(
                    artifacts / "concurrent" / name,
                    artifacts / "ordered" / name,
                )
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_identity_drift_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            identities = Path(directory) / "evidence-identities.json"
            identities.write_bytes(
                bounded_workbench.EVIDENCE_IDENTITIES_PATH.read_bytes() + b"\n"
            )
            with patch.object(
                bounded_workbench,
                "EVIDENCE_IDENTITIES_PATH",
                identities,
            ):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_reference_link_drift_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference-links.json"
            path.write_bytes(
                bounded_workbench.CORE30_REFERENCE_LINKS_PATH.read_bytes()
                + b"\n"
            )
            with patch.object(
                bounded_workbench,
                "CORE30_REFERENCE_LINKS_PATH",
                path,
            ):
                response = self._request_reference()
        self._assert_evidence_unavailable(response)

    def test_reference_decision_drift_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage4-oracle-decision.json"
            path.write_bytes(
                bounded_workbench.CORE30_STAGE4_DECISION_PATH.read_bytes()
                + b"\n"
            )
            with patch.object(
                bounded_workbench,
                "CORE30_STAGE4_DECISION_PATH",
                path,
            ):
                response = self._request_reference()
        self._assert_evidence_unavailable(response)

    def test_artifact_addition_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            (
                root / "backend-artifacts" / "ordered" / "extra.txt"
            ).write_text("unexpected")
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_artifact_deletion_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            (
                root
                / "backend-artifacts"
                / "ordered"
                / "classification.json"
            ).unlink()
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_artifact_byte_drift_returns_controlled_unavailable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_corpus(directory)
            artifact = (
                root
                / "backend-artifacts"
                / "ordered"
                / "classification.json"
            )
            artifact.write_bytes(artifact.read_bytes() + b"\n")
            with patch.object(bounded_workbench, "CORPUS_ROOT", root):
                response = self._request_case()
        self._assert_evidence_unavailable(response)

    def test_invalid_fsir_never_falls_back_to_prose(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={"source": "canonical_fsir", "fsir": {"prose": "transfer"}},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "invalid_fsir")

    def test_oversized_fsir_is_rejected_before_validation(self):
        response = self.client.post(
            "/api/bounded-workbench",
            json={
                "source": "canonical_fsir",
                "fsir": {
                    "padding": "x"
                    * (api_index.request_limits()["fsir_json_bytes"] + 1)
                },
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("fsir exceeds", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
