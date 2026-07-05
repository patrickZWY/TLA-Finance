import unittest

from safety.models import SafetyInputError, load_actions
from safety.transformer import _normalize_extracted_actions


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
