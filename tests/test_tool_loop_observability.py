import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from agents import tool_loop

    TOOL_LOOP_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - exercised as a skip condition.
    tool_loop = None
    TOOL_LOOP_IMPORT_ERROR = exc


class FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"action":"call_tool","tool":"noop","args":{}}',
                    ),
                ),
            ],
        )


class FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


@unittest.skipIf(TOOL_LOOP_IMPORT_ERROR is not None, f"Tool-loop dependencies unavailable: {TOOL_LOOP_IMPORT_ERROR}")
class ToolLoopObservabilityTests(unittest.TestCase):
    def test_tool_loop_timeout_logs_max_step_outcome(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "No-op tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"}, clear=False):
            with patch.object(tool_loop, "OpenAI", FakeOpenAI):
                with patch.object(tool_loop, "MAX_STEPS", 2):
                    with self.assertLogs(tool_loop.__name__, level="INFO") as captured:
                        result = tool_loop.run("system", "task", tools, lambda name, args: "{}")

        self.assertIn("unable to complete", result)
        records = [json.loads(record.getMessage()) for record in captured.records]
        outcome = [record for record in records if record["event"] == "tool_loop.outcome"][-1]
        self.assertEqual(outcome["outcome"], "max_steps")
        self.assertEqual(outcome["steps"], 2)


if __name__ == "__main__":
    unittest.main()
