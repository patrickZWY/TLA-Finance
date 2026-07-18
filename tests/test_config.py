import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import (
    DEFAULT_LOCAL_API_KEY,
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    allowed_origins,
    has_openai_api_key,
    openai_api_key,
    openai_base_url,
    openai_chat_options,
    openai_client,
    openai_disable_thinking_enabled,
    openai_json_mode_enabled,
    openai_max_retries,
    openai_model,
    openai_timeout_seconds,
    safety_subprocess_timeout_seconds,
    trusted_hosts,
)


class ConfigTests(unittest.TestCase):
    def test_openai_api_key_is_detected(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            self.assertTrue(has_openai_api_key())

    def test_missing_openai_key_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(has_openai_api_key())

    def test_local_openai_compatible_endpoint_counts_as_llm_config(self):
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "http://localhost:11434/v1"}, clear=True):
            self.assertTrue(has_openai_api_key())
            self.assertEqual(openai_base_url(), "http://localhost:11434/v1")
            self.assertEqual(openai_api_key(), DEFAULT_LOCAL_API_KEY)

    def test_default_openai_model_can_be_overridden(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(openai_model(), DEFAULT_OPENAI_MODEL)
        with patch.dict(os.environ, {"OPENAI_MODEL": "custom-model"}, clear=True):
            self.assertEqual(openai_model(), "custom-model")

    def test_json_mode_can_be_disabled_for_local_servers(self):
        with patch.dict(os.environ, {"OPENAI_JSON_MODE": "0"}, clear=True):
            self.assertFalse(openai_json_mode_enabled())

    def test_reasoning_effort_is_added_when_configured(self):
        with patch.dict(os.environ, {"OPENAI_REASONING_EFFORT": "none"}, clear=True):
            self.assertEqual(openai_chat_options(model="m")["reasoning_effort"], "none")

    def test_disable_thinking_adds_vllm_chat_template_option(self):
        with patch.dict(os.environ, {"OPENAI_DISABLE_THINKING": "1"}, clear=True):
            self.assertTrue(openai_disable_thinking_enabled())
            options = openai_chat_options(model="qwen3-32b")
        self.assertEqual(
            options["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False}},
        )

    def test_chat_options_preserve_explicit_response_format_and_extra_body(self):
        schema = object()
        with patch.dict(os.environ, {"OPENAI_DISABLE_THINKING": "1"}, clear=True):
            options = openai_chat_options(
                response_format=schema,
                extra_body={"top_k": 20, "chat_template_kwargs": {"custom": True}},
            )
        self.assertIs(options["response_format"], schema)
        self.assertEqual(options["extra_body"]["top_k"], 20)
        self.assertEqual(
            options["extra_body"]["chat_template_kwargs"],
            {"custom": True, "enable_thinking": False},
        )

    def test_openai_network_limits_default_and_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(openai_timeout_seconds(), DEFAULT_OPENAI_TIMEOUT_SECONDS)
            self.assertEqual(openai_max_retries(), DEFAULT_OPENAI_MAX_RETRIES)
        with patch.dict(
            os.environ,
            {"OPENAI_TIMEOUT_SECONDS": "45.5", "OPENAI_MAX_RETRIES": "0"},
            clear=True,
        ):
            self.assertEqual(openai_timeout_seconds(), 45.5)
            self.assertEqual(openai_max_retries(), 0)

    def test_openai_client_uses_remote_endpoint_and_network_limits(self):
        client_class = MagicMock()
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "secret-test-key",
                "OPENAI_BASE_URL": "http://127.0.0.1:18000/v1",
                "OPENAI_TIMEOUT_SECONDS": "30",
                "OPENAI_MAX_RETRIES": "0",
            },
            clear=True,
        ):
            with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=client_class)}):
                openai_client()
        client_class.assert_called_once_with(
            api_key="secret-test-key",
            base_url="http://127.0.0.1:18000/v1",
            timeout=30.0,
            max_retries=0,
        )

    def test_default_allowed_origins_are_local(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(allowed_origins(), ["http://127.0.0.1:8000", "http://localhost:8000"])

    def test_cloudflare_hostname_drives_origin_and_host_defaults(self):
        with patch.dict(os.environ, {"CLOUDFLARE_HOSTNAME": "automata-demo.example.com"}, clear=True):
            self.assertIn("https://automata-demo.example.com", allowed_origins())
            self.assertIn("automata-demo.example.com", trusted_hosts())
            self.assertIn("localhost", trusted_hosts())

    def test_public_demo_and_cloudflare_hostnames_are_allowed_together(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_DEMO_HOSTNAME": "demo.example.com",
                "CLOUDFLARE_HOSTNAME": "live-demo.example.com",
            },
            clear=True,
        ):
            self.assertIn("https://demo.example.com", allowed_origins())
            self.assertIn("https://live-demo.example.com", allowed_origins())
            self.assertIn("demo.example.com", trusted_hosts())
            self.assertIn("live-demo.example.com", trusted_hosts())

    def test_explicit_origin_and_host_config_is_respected(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_ORIGINS": "https://demo.example.com, http://localhost:8000",
                "ALLOWED_HOSTS": "demo.example.com,localhost",
            },
            clear=True,
        ):
            self.assertEqual(allowed_origins(), ["https://demo.example.com", "http://localhost:8000"])
            self.assertEqual(trusted_hosts(), ["demo.example.com", "localhost"])

    def test_tla_timeout_defaults_and_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(safety_subprocess_timeout_seconds("tlc"), 60)
        with patch.dict(os.environ, {"SAFETY_TLA_TIMEOUT_SECONDS": "7"}, clear=True):
            self.assertEqual(safety_subprocess_timeout_seconds("tlc"), 7)
        with patch.dict(
            os.environ,
            {"SAFETY_TLA_TIMEOUT_SECONDS": "7", "SAFETY_TLC_TIMEOUT_SECONDS": "3"},
            clear=True,
        ):
            self.assertEqual(safety_subprocess_timeout_seconds("tlc"), 3)


if __name__ == "__main__":
    unittest.main()
