import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
FIXTURES = json.loads(
    (ROOT / "public" / "workbench-demo-fixtures.json").read_text(encoding="utf-8")
)["fixtures"]


class BoundedAgentWorkbenchTests(unittest.TestCase):
    def test_existing_semantic_check_contract_is_preserved(self):
        self.assertIn("fetch('/api/semantic-check'", HTML)
        for field in (
            "user_message",
            "finance_advice",
            "policy",
            "run_model_checker",
        ):
            self.assertIn(field, HTML)

    def test_agreed_ui_state_matrix_is_explicit(self):
        for state in (
            "clarification_required",
            "ready_for_review",
            "verification_running",
            "violation_found",
            "verification_unavailable",
            "revision_proposed",
            "reverification_required",
            "checks_passed",
            "bounded_approval_required",
            "stopped",
        ):
            self.assertIn(state, HTML)

    def test_review_and_agent_controls_are_present(self):
        for control_id in (
            'id="editGoalBtn"',
            'id="stopAgentBtn"',
            'id="revisionBtn"',
            'id="boundedApprovalBtn"',
            'id="fsirList"',
            'id="blockingQuestions"',
            'id="activityList"',
        ):
            self.assertIn(control_id, HTML)
        for review_action in ("approve", "edit", "reject"):
            self.assertIn(f"['{review_action}'", HTML)

    def test_verdict_exposes_bounded_provenance(self):
        for field in ("property:", "backend:", "bounds:", "model:"):
            self.assertIn(field, HTML)
        self.assertIn("No configured guardrail was violated", HTML)
        self.assertIn("not a general claim of financial safety", HTML)

    def test_hero_fixture_matrix(self):
        self.assertEqual(
            set(FIXTURES),
            {"hero_safe", "hero_unsafe", "hero_clarification"},
        )
        self.assertTrue(FIXTURES["hero_safe"]["safe_to_execute"])
        self.assertEqual(FIXTURES["hero_safe"]["tlc"]["status"], "passed")
        self.assertFalse(FIXTURES["hero_unsafe"]["safe_to_execute"])
        self.assertEqual(FIXTURES["hero_unsafe"]["tlc"]["status"], "failed")
        self.assertEqual(
            FIXTURES["hero_clarification"]["decision"], "extraction_failed"
        )
        self.assertEqual(
            FIXTURES["hero_clarification"]["tlc"]["status"], "skipped"
        )

    def test_unsafe_fixture_has_shortest_counterexample_fields(self):
        journey = FIXTURES["hero_unsafe"]["violation_visualization"]["journey"]
        self.assertEqual(journey["first_violating_state"], 1)
        self.assertEqual(journey["counterexample_path"], [0, 1])
        self.assertEqual(
            journey["nodes"][1]["violations"][0]["code"],
            "negative_source_balance",
        )

    def test_accessibility_and_responsive_contract(self):
        for marker in (
            'aria-live="polite"',
            'role="alert"',
            "prefers-reduced-motion",
            "focus-visible",
            "@media (max-width: 620px)",
        ):
            self.assertIn(marker, HTML)

    def test_verifier_status_is_neutral_until_evidence_exists(self):
        self.assertIn(
            '<span class="badge warn" id="systemHealth">Verifier status not checked</span>',
            HTML,
        )
        self.assertNotIn("Local verifier ready", HTML)
        self.assertIn("setSystemHealth('Verifier responded · inspect evidence', 'ok')", HTML)
        self.assertIn("setSystemHealth('Verifier unavailable', 'bad')", HTML)

    def test_local_draft_retention_is_disclosed_and_clearable(self):
        self.assertIn("stored in this browser until you clear them", HTML)
        self.assertIn('id="clearLocalDataBtn"', HTML)
        clear_body = HTML.split("function clearLocalData() {", 1)[1].split(
            "function setSystemHealth", 1
        )[0]
        self.assertIn("window.confirm(", clear_body)
        self.assertGreaterEqual(
            clear_body.count("localStorage.removeItem(STORAGE_KEY)"), 2
        )
        for reset_marker in (
            "loadExample()",
            "resetReviewSurface()",
            "activity = []",
            "currentResult = null",
            "fixtureReplay",
            "runTlc",
        ):
            self.assertIn(reset_marker, clear_body)


if __name__ == "__main__":
    unittest.main()
