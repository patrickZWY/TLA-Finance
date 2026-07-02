import os
import unittest
from unittest.mock import patch

from config import (
    DEFAULT_LOCAL_API_KEY,
    DEFAULT_OPENAI_MODEL,
    allowed_origins,
    has_openai_api_key,
    openai_api_key,
    openai_base_url,
    openai_chat_options,
    openai_json_mode_enabled,
    openai_model,
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

    def test_default_allowed_origins_are_local(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(allowed_origins(), ["http://127.0.0.1:8000", "http://localhost:8000"])

    def test_cloudflare_hostname_drives_origin_and_host_defaults(self):
        with patch.dict(os.environ, {"CLOUDFLARE_HOSTNAME": "automata-demo.example.com"}, clear=True):
            self.assertIn("https://automata-demo.example.com", allowed_origins())
            self.assertIn("automata-demo.example.com", trusted_hosts())
            self.assertIn("localhost", trusted_hosts())

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
