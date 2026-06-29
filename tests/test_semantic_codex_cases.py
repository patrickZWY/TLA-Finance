import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from safety.agent import TlaSafetyAgent
from safety.models import FinanceAction, load_actions


ROOT = Path(__file__).resolve().parents[1]


class CodexGeneratedActionTransformer:
    """Offline stand-in for the live OpenAI semantic action extractor."""

    def __init__(self, generated_actions: dict):
        self.actions = load_actions(generated_actions, allow_empty=True)
        self.last_usage_estimate = {
            "model": "local-codex-fixture",
            "estimated_total_token_ceiling": 0,
        }

    def transform(self, finance_agent_output: str) -> list[FinanceAction]:
        if "```finance-actions" in finance_agent_output:
            raise AssertionError("semantic cases should use natural prose, not fenced action blocks")
        return self.actions


def load_fixture_json(name: str):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


class SemanticCodexCaseTests(unittest.TestCase):
    def test_codex_generated_actions_drive_safety_gate_from_natural_prose(self):
        cases = load_fixture_json("semantic_codex_cases.json")
        self.assertGreaterEqual(len(cases), 4)

        with TemporaryDirectory() as tmpdir:
            for case in cases:
                with self.subTest(case=case["name"]):
                    natural_agent_output = (
                        "User request:\n"
                        f"{case['user_request']}\n\n"
                        "Finance agent response:\n"
                        f"{case['finance_agent_response']}"
                    )
                    policy = load_fixture_json(case["policy"])
                    transformer = CodexGeneratedActionTransformer(case["codex_generated_actions"])
                    agent = TlaSafetyAgent(artifact_root=Path(tmpdir), transformer=transformer)

                    result = agent.check(
                        natural_agent_output,
                        policy,
                        run_name=case["name"],
                        run_model_checker=False,
                    )

                    codes = {finding.code for finding in result.findings}
                    self.assertEqual(codes, set(case["expected_finding_codes"]))
                    self.assertEqual(
                        result.safe_to_execute,
                        not case["expected_finding_codes"],
                    )
                    self.assertEqual(
                        json.loads((result.artifact_dir / "normalized_actions.json").read_text(encoding="utf-8")),
                        case["codex_generated_actions"],
                    )


if __name__ == "__main__":
    unittest.main()
