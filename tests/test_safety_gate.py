import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from safety.agent import TlaSafetyAgent, run
from safety.models import FinanceAction, SafetyPolicy, load_actions
from safety.tla_generator import generate_tla
from safety.transformer import ExplicitRequestActionTransformer, FinanceActionsBlockTransformer, estimate_transform_tokens
from safety.validator import evaluate_policy


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def load_text_fixture(name: str) -> str:
    return (ROOT / "fixtures" / name).read_text(encoding="utf-8")


class SafetyGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = SafetyPolicy.from_json(load_fixture("policy.dev.json"))
        self.complex_policy = SafetyPolicy.from_json(load_fixture("policy.complex_budget700_item400.json"))
        self.flow_policy = SafetyPolicy.from_json(load_fixture("policy.flow_budget600_item300.json"))

    def test_safe_actions_have_no_policy_findings(self):
        actions = load_actions(load_fixture("actions.safe.json"))
        self.assertEqual(evaluate_policy(actions, self.policy), [])

    def test_budget_violation_is_detected(self):
        actions = load_actions(load_fixture("actions.budget_violation.json"))
        codes = {finding.code for finding in evaluate_policy(actions, self.policy)}
        self.assertIn("budget_exceeded", codes)

    def test_destination_violation_is_detected(self):
        actions = load_actions(load_fixture("actions.destination_violation.json"))
        codes = {finding.code for finding in evaluate_policy(actions, self.policy)}
        self.assertIn("disallowed_destination", codes)

    def test_balance_violation_is_detected(self):
        actions = load_actions(load_fixture("actions.balance_violation.json"))
        codes = {finding.code for finding in evaluate_policy(actions, self.policy)}
        self.assertIn("negative_source_balance", codes)

    def test_tla_generator_emits_pluscal_and_tlc_config(self):
        actions = load_actions(load_fixture("actions.safe.json"))
        generated = generate_tla(actions, self.policy, "FinanceSafety_Test")
        self.assertIn("--algorithm FinanceSafety", generated.tla_text)
        self.assertIn("NoDetectedViolations", generated.tla_text)
        self.assertIn("MaxActionAmount", generated.tla_text)
        self.assertIn("NoActionAboveIndividualLimit", generated.tla_text)
        self.assertIn("SPECIFICATION Spec", generated.cfg_text)
        self.assertIn("Actions ==", generated.tla_text)

    def test_tla_safety_agent_returns_safe_decision_for_safe_actions(self):
        with TemporaryDirectory() as tmpdir:
            agent = TlaSafetyAgent(artifact_root=Path(tmpdir))
            result = agent.check(
                json.dumps(load_fixture("actions.safe.json")),
                self.policy,
                run_name="safe-agent-test",
                run_model_checker=False,
            )
            self.assertTrue(result.safe_to_execute)
            self.assertEqual(result.decision, "safe")
            self.assertFalse(result.requires_user_decision)
            self.assertTrue((Path(tmpdir) / "safe-agent-test" / "report.json").exists())

    def test_tla_safety_agent_requires_decision_for_unsafe_actions(self):
        with TemporaryDirectory() as tmpdir:
            agent = TlaSafetyAgent(artifact_root=Path(tmpdir))
            result = agent.check(
                json.dumps(load_fixture("actions.destination_violation.json")),
                self.policy,
                run_name="unsafe-agent-test",
                run_model_checker=False,
            )
            self.assertFalse(result.safe_to_execute)
            self.assertEqual(result.decision, "requires_user_decision")
            self.assertTrue(result.requires_user_decision)

    def test_tla_safety_agent_honors_user_continue_decision(self):
        with TemporaryDirectory() as tmpdir:
            report = run(
                json.dumps(load_fixture("actions.destination_violation.json")),
                self.policy,
                run_name="continue-agent-test",
                artifact_root=Path(tmpdir),
                run_model_checker=False,
                user_decision="continue",
            )
            self.assertTrue(report["safe_to_execute"])
            self.assertEqual(report["decision"], "continue")

    def test_tla_safety_agent_accepts_no_executable_actions(self):
        class EmptyTransformer:
            last_usage_estimate = {"estimated_total_token_ceiling": 123}

            def transform(self, finance_agent_output: str) -> list[FinanceAction]:
                return []

        with TemporaryDirectory() as tmpdir:
            agent = TlaSafetyAgent(artifact_root=Path(tmpdir), transformer=EmptyTransformer())
            result = agent.check(
                "Educational recommendation only.",
                self.policy,
                run_name="empty-actions-test",
                run_model_checker=False,
            )
            self.assertTrue(result.safe_to_execute)
            self.assertEqual(result.decision, "safe")
            self.assertEqual(result.transformer_usage["estimated_total_token_ceiling"], 123)

    def test_transformer_token_estimate_has_bounded_output_cap(self):
        estimate = estimate_transform_tokens("system", "finance output", 512, "gpt-4o-mini")
        self.assertEqual(estimate["max_output_tokens"], 512)
        self.assertLess(estimate["estimated_total_token_ceiling"], 600)

    def test_finance_actions_block_parser_accepts_benign_empty_recommendation(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.benign.empty.md"))
        self.assertEqual(actions, [])

    def test_finance_actions_block_parser_extracts_safe_actions(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.benign.safe_actions.md"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(evaluate_policy(actions, self.policy), [])

    def test_finance_actions_block_parser_rejects_missing_block(self):
        transformer = FinanceActionsBlockTransformer()
        with self.assertRaises(Exception):
            transformer.transform(load_text_fixture("finance_reply.missing_block.md"))

    def test_benign_and_bad_finance_reply_fixtures_match_policy_expectations(self):
        transformer = FinanceActionsBlockTransformer()
        benign = transformer.transform(load_text_fixture("finance_reply.benign.safe_actions.md"))
        self.assertEqual(evaluate_policy(benign, self.policy), [])

        bad_destination = transformer.transform(load_text_fixture("finance_reply.bad_destination.md"))
        destination_codes = {finding.code for finding in evaluate_policy(bad_destination, self.policy)}
        self.assertIn("disallowed_destination", destination_codes)

        bad_budget = transformer.transform(load_text_fixture("finance_reply.bad_budget.md"))
        budget_codes = {finding.code for finding in evaluate_policy(bad_budget, self.policy)}
        self.assertIn("budget_exceeded", budget_codes)

        bad_balance = transformer.transform(load_text_fixture("finance_reply.bad_balance.md"))
        balance_codes = {finding.code for finding in evaluate_policy(bad_balance, self.policy)}
        self.assertIn("negative_source_balance", balance_codes)

    def test_complex_benign_lists_do_not_trigger_policy_findings(self):
        transformer = FinanceActionsBlockTransformer()
        for fixture in (
            "finance_reply.complex_benign.multi_action.md",
            "finance_reply.complex_benign.edge_budget.md",
        ):
            with self.subTest(fixture=fixture):
                actions = transformer.transform(load_text_fixture(fixture))
                self.assertEqual(evaluate_policy(actions, self.complex_policy), [])

    def test_complex_bad_cumulative_budget_triggers_budget_only(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.complex_bad.cumulative_budget.md"))
        codes = {finding.code for finding in evaluate_policy(actions, self.complex_policy)}
        self.assertIn("budget_exceeded", codes)
        self.assertNotIn("individual_action_limit_exceeded", codes)

    def test_complex_bad_individual_item_triggers_item_limit_only(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.complex_bad.individual_item.md"))
        codes = {finding.code for finding in evaluate_policy(actions, self.complex_policy)}
        self.assertIn("individual_action_limit_exceeded", codes)
        self.assertNotIn("budget_exceeded", codes)

    def test_complex_bad_combined_budget_and_item_triggers_both(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.complex_bad.combined_budget_and_item.md"))
        codes = {finding.code for finding in evaluate_policy(actions, self.complex_policy)}
        self.assertIn("budget_exceeded", codes)
        self.assertIn("individual_action_limit_exceeded", codes)

    def test_complex_bad_destination_and_balance_triggers_expected_findings(self):
        transformer = FinanceActionsBlockTransformer()
        destination_actions = transformer.transform(load_text_fixture("finance_reply.complex_bad.destination_and_budget.md"))
        destination_codes = {finding.code for finding in evaluate_policy(destination_actions, self.complex_policy)}
        self.assertIn("disallowed_destination", destination_codes)
        self.assertIn("budget_exceeded", destination_codes)

        balance_actions = transformer.transform(load_text_fixture("finance_reply.complex_bad.balance.md"))
        balance_codes = {finding.code for finding in evaluate_policy(balance_actions, self.complex_policy)}
        self.assertIn("negative_source_balance", balance_codes)
        self.assertNotIn("budget_exceeded", balance_codes)

    def test_account_flow_credits_destination_before_later_debit(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.flow_benign.transfer_then_buy.md"))
        self.assertEqual(evaluate_policy(actions, self.flow_policy), [])

    def test_account_flow_detects_bad_action_order(self):
        transformer = FinanceActionsBlockTransformer()
        actions = transformer.transform(load_text_fixture("finance_reply.flow_bad.buy_before_transfer.md"))
        codes = {finding.code for finding in evaluate_policy(actions, self.flow_policy)}
        self.assertIn("negative_source_balance", codes)

    def test_explicit_request_fallback_parses_concrete_actions_and_typo(self):
        transformer = ExplicitRequestActionTransformer()
        actions = transformer.transform(
            "now transfare $7000 from checking to unknownGuy100, "
            "then buy $200 of VTI from brokerage into savings."
        )
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].action, "transfer")
        self.assertEqual(actions[0].amount, 7000)
        self.assertEqual(actions[0].source, "checking")
        self.assertEqual(actions[0].destination, "unknownGuy100")
        self.assertEqual(actions[1].action, "buy")
        self.assertEqual(actions[1].source, "brokerage")
        self.assertEqual(actions[1].destination, "savings")

    def test_explicit_request_fallback_parses_safe_transfer_phrase(self):
        transformer = ExplicitRequestActionTransformer()
        actions = transformer.transform("i want to transfer 200 dollars from checking to savings account")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "transfer")
        self.assertEqual(actions[0].amount, 200)
        self.assertEqual(actions[0].source, "checking")
        self.assertEqual(actions[0].destination, "savings")

    def test_agents_wrapper_supports_structured_json_mode(self):
        from agents.tla_safety_agent import run as run_tla_agent

        with TemporaryDirectory() as tmpdir:
            report = run_tla_agent(
                json.dumps(load_fixture("actions.safe.json")),
                self.policy,
                run_name="wrapper-json-test",
                artifact_root=Path(tmpdir),
                run_model_checker=False,
                structured_json=True,
            )
            self.assertTrue(report["safe_to_execute"])
            self.assertEqual(report["decision"], "safe")


if __name__ == "__main__":
    unittest.main()
