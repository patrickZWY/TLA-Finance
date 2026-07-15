import unittest

from safety.models import FinanceAction, SafetyPolicy, dump_actions, load_actions
from safety.tla_generator import generate_tla
from safety.validator import evaluate_policy


class ChoiceBranchTests(unittest.TestCase):
    def setUp(self):
        self.policy = SafetyPolicy.from_json({
            "budget": 600,
            "max_individual_action_amount": 300,
            "account_balances": {"checking": 300, "brokerage": 0},
            "allowed_destination_accounts": ["brokerage"],
            "allowed_action_types": ["buy", "transfer"],
        })
        self.actions = [
            FinanceAction("transfer", 300, "checking", "brokerage", "fund first"),
            FinanceAction("buy", 300, "brokerage", "brokerage", "fund first"),
            FinanceAction("buy", 300, "brokerage", "brokerage", "buy first"),
            FinanceAction("transfer", 300, "checking", "brokerage", "buy first"),
        ]

    def test_one_unsafe_choice_blocks_the_whole_plan(self):
        findings = evaluate_policy(self.actions, self.policy)
        self.assertEqual([finding.code for finding in findings], ["negative_source_balance"])
        self.assertEqual(findings[0].choice, "buy first")

    def test_choice_model_uses_pluscal_nondeterminism(self):
        generated = generate_tla(self.actions, self.policy, "ChoiceDemo")
        self.assertIn("ActionPlans ==", generated.tla_text)
        self.assertIn("either", generated.tla_text)
        self.assertIn("or", generated.tla_text)
        self.assertIn("selectedChoice", generated.tla_text)

    def test_partially_tagged_choices_are_rejected(self):
        actions = [self.actions[0], FinanceAction("buy", 300, "brokerage", "brokerage")]
        self.assertEqual(evaluate_policy(actions, self.policy)[0].code, "invalid_choice_structure")

    def test_clean_choices_json_round_trips_to_branch_actions(self):
        raw = {
            "choices": [
                {"name": "fund first", "actions": [{"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"}]},
                {"name": "buy first", "actions": [{"action": "buy", "amount": 300, "from": "brokerage", "to": "brokerage"}]},
            ]
        }
        actions = load_actions(raw)
        self.assertEqual([action.choice for action in actions], ["fund first", "buy first"])
        self.assertEqual(dump_actions(actions), raw)
