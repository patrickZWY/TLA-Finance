import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SAFETY_RUN_TLC", "0")
os.environ.setdefault("SAFETY_ACTION_TRANSFORMER", "block")

try:
    from fastapi.testclient import TestClient

    from agents import storage
    from api import index as api_index

    API_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - exercised as a skip condition.
    TestClient = None
    storage = None
    api_index = None
    API_IMPORT_ERROR = exc


def load_json_fixture(name: str):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def load_text_fixture(name: str) -> str:
    return (ROOT / "fixtures" / name).read_text(encoding="utf-8")


def fake_openai_client_with_router_content(content: str):
    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=content)),
                ],
            )

    class FakeOpenAI:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    return FakeOpenAI()


@unittest.skipIf(API_IMPORT_ERROR is not None, f"API dependencies unavailable: {API_IMPORT_ERROR}")
class ApiSafetyFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api_index.app)

    def tearDown(self):
        storage.clear_session()

    def test_pending_safety_continue_returns_original_reply(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "continue",
                "session_data": {
                    "pending_safety_review": {
                        "approved_reply": "Original finance reply.",
                    }
                },
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Safety override recorded", payload["reply"])
        self.assertIn("Original finance reply.", payload["reply"])
        self.assertNotIn("pending_safety_review", payload["session_data"])

    def test_pending_safety_stop_terminates_plan(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "stop",
                "session_data": {
                    "pending_safety_review": {
                        "approved_reply": "Original finance reply.",
                    }
                },
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Plan terminated", payload["reply"])
        self.assertNotIn("pending_safety_review", payload["session_data"])

    def test_pending_safety_blocks_new_message_until_decision(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "I spent $120 on groceries and set a $300/month grocery limit",
                "session_data": {
                    "pending_safety_review": {
                        "approved_reply": "Original risky finance reply.",
                    }
                },
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("did not process your latest message yet", payload["reply"])
        self.assertIn("pending_safety_review", payload["session_data"])

    def test_chat_route_returns_http_error_when_backend_fails(self):
        with patch.object(api_index, "_chat", side_effect=RuntimeError("simulated failure")):
            response = self.client.post(
                "/api/chat",
                json={"message": "hello", "session_data": {}, "history": []},
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("Chat request failed", response.json()["detail"])

    def test_chat_request_logs_selected_agents_and_safety_status(self):
        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"}, clear=False):
            with patch.object(api_index, "openai_client", return_value=fake_openai_client_with_router_content('{"agents":["budget"],"task":"summarize"}')):
                with patch.dict(api_index.AGENT_MAP, {"budget": (lambda task: "Budget reply.", "Budget")}):
                    with patch.object(api_index, "_check_reply_with_tla_safety", return_value=None):
                        with self.assertLogs(api_index.__name__, level="INFO") as captured:
                            response = self.client.post(
                                "/api/chat",
                                json={"message": "hello", "session_data": {}, "history": []},
                            )
        self.assertEqual(response.status_code, 200)
        records = [json.loads(record.getMessage()) for record in captured.records]
        processed = next(record for record in records if record["event"] == "api.chat.processed")
        self.assertEqual(processed["selected_agents"], ["Budget"])
        self.assertEqual(processed["safety_status"], "passed")

    def test_malformed_router_json_logs_parse_failure_and_falls_back(self):
        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"}, clear=False):
            with patch.object(api_index, "openai_client", return_value=fake_openai_client_with_router_content("{not-json")):
                with patch.dict(api_index.AGENT_MAP, {"budget": (lambda task: "Budget reply.", "Budget")}):
                    with patch.object(api_index, "_check_reply_with_tla_safety", return_value=None):
                        with self.assertLogs(api_index.__name__, level="INFO") as captured:
                            response = self.client.post(
                                "/api/chat",
                                json={"message": "hello", "session_data": {}, "history": []},
                            )
        self.assertEqual(response.status_code, 200)
        records = [json.loads(record.getMessage()) for record in captured.records]
        events = {record["event"] for record in records}
        self.assertIn("api.router.parse_failure", events)
        processed = next(record for record in records if record["event"] == "api.chat.processed")
        self.assertEqual(processed["requested_agents"], ["budget"])

    def test_safety_gate_allows_safe_finance_actions_block(self):
        storage.init_session({"safety_policy": load_json_fixture("policy.flow_budget600_item300.json")})
        warning = api_index._check_reply_with_tla_safety(
            "Please make the safe flow plan.",
            load_text_fixture("finance_reply.flow_benign.transfer_then_buy.md"),
        )
        self.assertIsNone(warning)

    def test_safety_gate_warns_on_bad_finance_actions_block(self):
        storage.init_session({"safety_policy": load_json_fixture("policy.complex_budget700_item400.json")})
        warning = api_index._check_reply_with_tla_safety(
            "Please make a risky plan.",
            load_text_fixture("finance_reply.complex_bad.combined_budget_and_item.md"),
        )
        self.assertIsNotNone(warning)
        self.assertIn("TLA+ Safety Warning", warning)
        self.assertIn("individual_action_limit_exceeded", warning)
        self.assertIn("budget_exceeded", warning)
        self.assertIn("pending_safety_review", storage.get_session())

    def test_safety_gate_warns_on_missing_finance_actions_block(self):
        storage.init_session({"safety_policy": load_json_fixture("policy.dev.json")})
        warning = api_index._check_reply_with_tla_safety(
            "Please transfer money.",
            load_text_fixture("finance_reply.missing_block.md"),
        )
        self.assertIsNotNone(warning)
        self.assertIn("finance_output_protocol_violation", warning)
        self.assertIn("finance-actions block", warning)

    def test_safety_gate_recovers_explicit_actions_when_finance_block_is_missing(self):
        storage.init_session({"safety_policy": load_json_fixture("policy.complex_budget700_item400.json")})
        warning = api_index._check_reply_with_tla_safety(
            "now transfare $7000 from checking to unknownGuy100, "
            "then buy $200 of VTI from brokerage into savings. please treat these as concrete actions.",
            "I cannot help with that request.",
        )
        self.assertIsNotNone(warning)
        self.assertIn("finance_output_protocol_violation", warning)
        self.assertIn("disallowed_destination", warning)
        self.assertIn("budget_exceeded", warning)
        self.assertIn("individual_action_limit_exceeded", warning)
        self.assertIn("negative_source_balance", warning)

    def test_safety_gate_allows_recovered_safe_actions_when_finance_block_is_missing(self):
        storage.init_session({"safety_policy": load_json_fixture("policy.complex_budget700_item400.json")})
        warning = api_index._check_reply_with_tla_safety(
            "i want to transfer 400 dollars from checking to brokerage",
            "I can help with that transfer.",
        )
        self.assertIsNone(warning)
        self.assertNotIn("pending_safety_review", storage.get_session())

    def test_bad_safety_demo_uses_fixture_and_surfaces_warning(self):
        response = self.client.post(
            "/api/demo/bad-suggestion",
            json={
                "example": "combined_budget_and_item",
                "session_data": {},
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("TLA+ Safety Warning", payload["reply"])
        self.assertIn("individual_action_limit_exceeded", payload["reply"])
        self.assertIn("budget_exceeded", payload["reply"])
        self.assertIn("pending_safety_review", payload["session_data"])
        self.assertEqual(payload["session_data"]["safety_policy"]["budget"], 700)

    def test_bad_safety_demo_rejects_unknown_fixture(self):
        response = self.client.post(
            "/api/demo/bad-suggestion",
            json={
                "example": "not_a_real_demo",
                "session_data": {},
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown bad safety demo", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
