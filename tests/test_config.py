import os
import unittest
from unittest.mock import patch

from config import DEFAULT_OPENAI_MODEL, has_openai_api_key, openai_model


class ConfigTests(unittest.TestCase):
    def test_openai_api_key_is_detected(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            self.assertTrue(has_openai_api_key())

    def test_missing_openai_key_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(has_openai_api_key())

    def test_default_openai_model_can_be_overridden(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(openai_model(), DEFAULT_OPENAI_MODEL)
        with patch.dict(os.environ, {"OPENAI_MODEL": "custom-model"}, clear=True):
            self.assertEqual(openai_model(), "custom-model")


if __name__ == "__main__":
    unittest.main()
