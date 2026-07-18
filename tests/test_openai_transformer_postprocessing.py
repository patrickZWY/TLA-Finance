import unittest
from types import SimpleNamespace
from unittest.mock import patch

from safety.models import SafetyInputError, load_actions
from safety.transformer import ExtractedAction, ExtractedPlan, OpenAIActionTransformer, _normalize_extracted_actions


class _FakeOllamaResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return (
            '{"message":{"content":'
            + __import__("json").dumps(self.content)
            + "}}"
        ).encode("utf-8")


class OpenAITransformerPostprocessingTests(unittest.TestCase):
    def test_normalizes_external_destination_case(self):
        source = "Wire 50 from checking to my cousin Alex for concert tickets."
        raw = {
            "actions": [
                {"action": "transfer", "amount": 50, "from": "checking", "to": "Alex"}
            ]
        }

        actions = load_actions(_normalize_extracted_actions(raw, source), allow_empty=True)

        self.assertEqual(actions[0].destination, "alex")

    def test_repairs_supported_colon_account_suffix(self):
        source = (
            "Grab 300 worth in the brokerage account now, and after that move 300 "
            "over from checking so the cash is back where it needs to be."
        )
        raw = {
            "actions": [
                {"action": "buy", "amount": 300, "from": "brokerage", "to": "broker:brokerage"},
                {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"},
            ]
        }

        actions = load_actions(_normalize_extracted_actions(raw, source), allow_empty=True)

        self.assertEqual(actions[0].destination, "brokerage")
        self.assertEqual(actions[1].destination, "brokerage")

    def test_rejects_unsupported_colon_account(self):
        source = "Transfer 100 from checking to savings."
        raw = {
            "actions": [
                {"action": "transfer", "amount": 100, "from": "checking", "to": "bank:routing"}
            ]
        }

        with self.assertRaises(SafetyInputError):
            _normalize_extracted_actions(raw, source)

    def test_rejects_amount_not_present_in_source_text(self):
        source = "Use 300 of brokerage cash to purchase VTI inside the brokerage account."
        raw = {
            "actions": [
                {"action": "buy", "amount": 301, "from": "brokerage", "to": "brokerage"}
            ]
        }

        with self.assertRaisesRegex(SafetyInputError, "amount 301"):
            _normalize_extracted_actions(raw, source)

    def test_rejects_substring_amount_not_present_as_standalone_amount(self):
        source = "First transfer 300 from checking, then buy 300 inside brokerage."
        raw = {
            "actions": [
                {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"},
                {"action": "buy", "amount": 30, "from": "brokerage", "to": "brokerage"},
            ]
        }

        with self.assertRaisesRegex(SafetyInputError, "amount 30"):
            _normalize_extracted_actions(raw, source)

    def test_ollama_retry_can_correct_validator_rejected_amount(self):
        source = "First move 300 from checking into brokerage, then buy 300 of VTI inside brokerage."
        first = """{
  "actions": [
    {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"},
    {"action": "buy", "amount": 30, "from": "brokerage", "to": "brokerage"}
  ]
}"""
        second = """{
  "actions": [
    {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"},
    {"action": "buy", "amount": 300, "from": "brokerage", "to": "brokerage"}
  ]
}"""
        transformer = OpenAIActionTransformer(model="qwen3:4b")

        with patch("safety.transformer.openai_base_url", return_value="http://localhost:11434/v1"):
            with patch(
                "safety.transformer.urllib.request.urlopen",
                side_effect=[_FakeOllamaResponse(first), _FakeOllamaResponse(second)],
            ):
                with self.assertRaisesRegex(SafetyInputError, "amount 30") as caught:
                    transformer._try_ollama_native_structured(source)
                actions = transformer._try_ollama_native_structured_retry(source, caught.exception)

        self.assertIsNotNone(actions)
        self.assertEqual([action.amount for action in actions or []], [300, 300])

    def test_openai_compatible_retry_corrects_actions_and_choices_conflict(self):
        source = (
            "Transfer 300 from checking to brokerage, then buy 200 of VTI "
            "inside the brokerage account."
        )
        rejected = {
            "actions": [
                {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"},
            ],
            "choices": [
                {
                    "name": "buy",
                    "actions": [
                        {"action": "buy", "amount": 200, "from": "brokerage", "to": "brokerage"},
                    ],
                },
            ],
        }
        corrected = (
            '{"actions":['
            '{"action":"transfer","amount":300,"from":"checking","to":"brokerage"},'
            '{"action":"buy","amount":200,"from":"brokerage","to":"brokerage"}'
            ']}'
        )

        class FakeParsed:
            def model_dump(self, **kwargs):
                return rejected

        class FakeStructuredCompletions:
            def parse(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=str(rejected), parsed=FakeParsed()))]
                )

        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=corrected))]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(
            beta=SimpleNamespace(
                chat=SimpleNamespace(completions=FakeStructuredCompletions()),
            ),
            chat=SimpleNamespace(completions=completions),
        )
        transformer = OpenAIActionTransformer(model="qwen3-32b")

        with patch("safety.transformer.has_openai_api_key", return_value=True):
            with patch("safety.transformer.openai_client", return_value=client):
                actions = transformer.transform(source)

        self.assertEqual([action.action for action in actions], ["transfer", "buy"])
        self.assertEqual(len(completions.calls), 1)
        correction = completions.calls[0]["messages"][-1]["content"]
        self.assertIn("choices JSON must not also contain an actions list", correction)
        self.assertIn("`then`", correction)

    def test_structured_actions_plan_excludes_absent_choices_before_validation(self):
        source = "Transfer 300 from checking to brokerage."
        parsed = ExtractedPlan(
            actions=[
                ExtractedAction(
                    action="transfer",
                    amount=300,
                    **{"from": "checking", "to": "brokerage"},
                )
            ]
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="valid", parsed=parsed))]
        )
        client = SimpleNamespace(
            beta=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(parse=lambda **kwargs: response),
                )
            )
        )
        transformer = OpenAIActionTransformer(model="qwen3-32b")

        actions = transformer._try_structured_parse(client, source)

        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].destination, "brokerage")

    def test_preserves_uppercase_holding_ticker(self):
        source = "Swap 100 from VTI to BND."
        raw = {
            "actions": [
                {"action": "swap", "amount": 100, "from": "VTI", "to": "BND"}
            ]
        }

        actions = load_actions(_normalize_extracted_actions(raw, source), allow_empty=True)

        self.assertEqual(actions[0].source, "VTI")
        self.assertEqual(actions[0].destination, "BND")


if __name__ == "__main__":
    unittest.main()
