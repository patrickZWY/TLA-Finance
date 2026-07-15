import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from safety.models import FinanceAction, SafetyPolicy
from safety.validator import evaluate_policy
from safety.visualization import build_violation_visualization, parse_tlc_dot


def policy(**overrides):
    raw = {
        "budget": 100,
        "max_individual_action_amount": 80,
        "account_balances": {"checking": 100, "brokerage": 0},
        "allowed_destination_accounts": ["brokerage"],
        "allowed_action_types": ["buy", "transfer"],
    }
    raw.update(overrides)
    return SafetyPolicy.from_json(raw)


class ViolationVisualizationTests(unittest.TestCase):
    def action(self, amount=50, source="checking", destination="brokerage", kind="transfer"):
        return FinanceAction(kind, amount, source, destination)

    def test_safe_actions_have_tlc_payload_but_no_counterexample(self):
        actions = [self.action(50)]
        graph = build_violation_visualization(actions, policy(), evaluate_policy(actions, policy()), tlc_status="skipped")
        self.assertIsNone(graph["journey"])
        self.assertEqual(graph["tlc_graph"]["status"], "unavailable")

    def test_budget_overflow_marks_first_unsafe_state(self):
        actions = [self.action(60), self.action(60)]
        graph = build_violation_visualization(actions, policy(), evaluate_policy(actions, policy()), tlc_status="skipped")
        self.assertEqual(graph["journey"]["first_violating_state"], 2)
        self.assertIn("budget_exceeded", [item["code"] for item in graph["journey"]["nodes"][2]["violations"]])

    def test_destination_limit_missing_source_and_negative_balance_are_explained(self):
        cases = [
            (self.action(10, destination="outside"), "disallowed_destination"),
            (self.action(90), "individual_action_limit_exceeded"),
            (self.action(10, source="missing"), "unknown_source_account"),
            (self.action(70), "negative_source_balance"),
        ]
        for action, code in cases:
            with self.subTest(code=code):
                active_policy = policy(account_balances={"checking": 50, "brokerage": 0}) if code == "negative_source_balance" else policy()
                graph = build_violation_visualization([action], active_policy, evaluate_policy([action], active_policy), tlc_status="skipped")
                self.assertIn(code, [item["code"] for item in graph["journey"]["nodes"][1]["violations"]])

    def test_twelve_step_route_marks_only_the_final_overdraft(self):
        route = [
            self.action(100, "checking", "brokerage"), self.action(50, "brokerage", "savings"),
            self.action(75, "checking", "emergency"), self.action(25, "emergency", "brokerage"),
            self.action(40, "brokerage", "savings"), self.action(30, "savings", "checking"),
            self.action(60, "checking", "brokerage"), self.action(20, "brokerage", "emergency"),
            self.action(10, "emergency", "savings"), self.action(15, "savings", "brokerage"),
            self.action(35, "brokerage", "checking"), self.action(80, "brokerage", "savings"),
        ]
        route_policy = policy(
            budget=600,
            max_individual_action_amount=100,
            account_balances={"checking": 1000, "brokerage": 0, "savings": 0, "emergency": 0},
            allowed_destination_accounts=["checking", "brokerage", "savings", "emergency"],
            allowed_action_types=["transfer"],
        )
        graph = build_violation_visualization(route, route_policy, evaluate_policy(route, route_policy), tlc_status="failed")
        self.assertEqual(graph["journey"]["first_violating_state"], 12)
        self.assertEqual(len(graph["journey"]["nodes"]), 13)

    def test_tlc_dot_is_exposed_only_as_parsed_local_data(self):
        dot = 'digraph DiskGraph {\n  0 [label="State 0"];\n  1 [label="State 1"];\n  0 -> 1 [label="Next"];\n}\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "graph.dot"
            path.write_text(dot, encoding="utf-8")
            actions = [self.action(101)]
            graph = build_violation_visualization(actions, policy(), evaluate_policy(actions, policy()), tlc_status="failed", dot_path=path)
        self.assertEqual(graph["tlc_graph"]["status"], "available")
        self.assertEqual(graph["tlc_graph"]["edges"][0]["label"], "Next")
        self.assertEqual(graph["tlc_graph"]["counterexample_node_ids"], ["0", "1"])
        with self.assertRaises(ValueError):
            parse_tlc_dot("not dot")

    def test_dot_style_declarations_are_not_states(self):
        nodes, _ = parse_tlc_dot('strict digraph G {\nedge [color="blue"]\n1 [label="state"]\n}')
        self.assertEqual(nodes, [{"id": "1", "label": "state"}])
