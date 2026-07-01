import os
import unittest
from unittest.mock import patch

from config import (
    DEFAULT_LOCAL_API_KEY,
    DEFAULT_OPENAI_MODEL,
    has_openai_api_key,
    openai_api_key,
    openai_base_url,
    openai_chat_options,
    openai_json_mode_enabled,
    openai_model,
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


if __name__ == "__main__":
    unittest.main()
