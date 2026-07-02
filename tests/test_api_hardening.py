import contextvars
import os
import unittest
from unittest.mock import patch


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


@unittest.skipIf(API_IMPORT_ERROR is not None, f"API dependencies unavailable: {API_IMPORT_ERROR}")
class ApiHardeningTests(unittest.TestCase):
    def setUp(self):
        api_index.rate_limiter.reset()
        storage.clear_session()
        self.client = TestClient(api_index.app)

    def tearDown(self):
        api_index.rate_limiter.reset()
        storage.clear_session()

    def test_health_returns_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_cors_allows_local_origin_and_rejects_unrelated_origin(self):
        allowed = self.client.get("/api/health", headers={"Origin": "http://localhost:8000"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:8000")

        rejected = self.client.get("/api/health", headers={"Origin": "https://attacker.example"})
        self.assertEqual(rejected.status_code, 200)
        self.assertIsNone(rejected.headers.get("access-control-allow-origin"))

    def test_host_validation_allows_local_hosts_and_rejects_random_host(self):
        for host in ("localhost", "127.0.0.1", "testserver"):
            with self.subTest(host=host):
                response = self.client.get("/api/health", headers={"Host": host})
                self.assertEqual(response.status_code, 200)

        rejected = self.client.get("/api/health", headers={"Host": "random.example.com"})
        self.assertEqual(rejected.status_code, 400)

    def test_chat_rate_limit_boundary_is_per_client(self):
        headers = {"CF-Connecting-IP": "203.0.113.10"}
        with patch.object(
            api_index,
            "_chat",
            return_value=api_index.ChatResponse(reply="ok", session_data={}, history=[]),
        ):
            for _ in range(5):
                response = self.client.post("/api/chat", json={"message": "hello"}, headers=headers)
                self.assertEqual(response.status_code, 200)

            limited = self.client.post("/api/chat", json={"message": "hello"}, headers=headers)
            self.assertEqual(limited.status_code, 429)

            other_client = self.client.post(
                "/api/chat",
                json={"message": "hello"},
                headers={"CF-Connecting-IP": "203.0.113.11"},
            )
            self.assertEqual(other_client.status_code, 200)

    def test_rate_limits_are_per_endpoint(self):
        headers = {"CF-Connecting-IP": "203.0.113.20"}
        policy = {
            "budget": 100,
            "account_balances": {"checking": 100},
            "allowed_destination_accounts": ["brokerage"],
        }
        with patch.object(
            api_index,
            "_chat",
            return_value=api_index.ChatResponse(reply="ok", session_data={}, history=[]),
        ), patch.object(api_index, "_semantic_check", return_value={"ok": True}):
            for _ in range(5):
                self.client.post("/api/chat", json={"message": "hello"}, headers=headers)

            chat_limited = self.client.post("/api/chat", json={"message": "hello"}, headers=headers)
            self.assertEqual(chat_limited.status_code, 429)

            semantic_allowed = self.client.post(
                "/api/semantic-check",
                json={"finance_advice": "No action.", "policy": policy},
                headers=headers,
            )
            self.assertEqual(semantic_allowed.status_code, 200)

    def test_oversized_chat_message_returns_413(self):
        limit = api_index.request_limits()["user_message_chars"]
        response = self.client.post("/api/chat", json={"message": "x" * (limit + 1)})
        self.assertEqual(response.status_code, 413)
        self.assertIn("message exceeds", response.json()["detail"])

    def test_oversized_history_returns_413(self):
        limit = api_index.request_limits()["history_items"]
        history = [{"role": "user", "content": "hello"} for _ in range(limit + 1)]
        response = self.client.post("/api/chat", json={"message": "hello", "history": history})
        self.assertEqual(response.status_code, 413)
        self.assertIn("history exceeds", response.json()["detail"])

    def test_oversized_semantic_advice_returns_413(self):
        limit = api_index.request_limits()["finance_advice_chars"]
        response = self.client.post(
            "/api/semantic-check",
            json={
                "finance_advice": "x" * (limit + 1),
                "policy": {
                    "budget": 100,
                    "account_balances": {"checking": 100},
                    "allowed_destination_accounts": ["brokerage"],
                },
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("finance_advice exceeds", response.json()["detail"])

    def test_oversized_policy_returns_413(self):
        limit = api_index.request_limits()["policy_json_bytes"]
        response = self.client.post(
            "/api/semantic-check",
            json={
                "finance_advice": "No action.",
                "policy": {
                    "budget": 100,
                    "account_balances": {"checking": 100},
                    "allowed_destination_accounts": ["brokerage"],
                    "padding": "x" * limit,
                },
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("policy exceeds", response.json()["detail"])

    def test_storage_session_state_is_context_local(self):
        ctx_one = contextvars.Context()
        ctx_two = contextvars.Context()
        ctx_one.run(
            storage.init_session,
            {
                "transactions": [{"id": "one"}],
                "safety_policy": {"budget": 1},
                "pending_safety_review": {"approved_reply": "one"},
            },
        )
        ctx_two.run(
            storage.init_session,
            {
                "transactions": [{"id": "two"}],
                "safety_policy": {"budget": 2},
                "pending_safety_review": {"approved_reply": "two"},
            },
        )

        def update_one() -> None:
            session = storage.get_session() or {}
            session["transactions"] = [{"id": "one-updated"}]
            session["safety_policy"] = {"budget": 3}
            storage.save(session)

        ctx_one.run(update_one)

        first = ctx_one.run(storage.get_session)
        second = ctx_two.run(storage.get_session)
        self.assertEqual(first["transactions"], [{"id": "one-updated"}])
        self.assertEqual(first["safety_policy"], {"budget": 3})
        self.assertEqual(second["transactions"], [{"id": "two"}])
        self.assertEqual(second["safety_policy"], {"budget": 2})
        self.assertEqual(second["pending_safety_review"]["approved_reply"], "two")


if __name__ == "__main__":
    unittest.main()
