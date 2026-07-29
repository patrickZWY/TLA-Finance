import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from safety.fsir import (
    FsirDocument,
    UnresolvedItem,
    dump_fsir,
    fsir_json_schema,
    fsir_to_legacy,
    legacy_to_fsir,
)
from scripts.migrate_semantic_cases_to_fsir import migrate_cases


ROOT = Path(__file__).resolve().parents[1]
LEGACY_CASES_PATH = ROOT / "fixtures" / "semantic_codex_cases.json"
FSIR_CASES_PATH = ROOT / "fixtures" / "fsir" / "semantic_codex_cases.fsir.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FsirFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy_cases = load_json(LEGACY_CASES_PATH)
        cls.fsir_suite = load_json(FSIR_CASES_PATH)
        cls.legacy_by_name = {case["name"]: case for case in cls.legacy_cases}
        cls.fsir_by_name = {case["name"]: case for case in cls.fsir_suite["cases"]}

    def test_all_twelve_seed_cases_parse_and_round_trip_legacy_payloads(self):
        self.assertEqual(self.fsir_suite["case_count"], 12)
        self.assertEqual(len(self.fsir_suite["cases"]), 12)

        for migrated in self.fsir_suite["cases"]:
            with self.subTest(case=migrated["name"]):
                document = FsirDocument(**migrated["fsir"])
                original = self.legacy_by_name[migrated["name"]]["codex_generated_actions"]
                self.assertEqual(fsir_to_legacy(document), original)

    def test_seed_migration_is_deterministic(self):
        regenerated = migrate_cases(self.legacy_cases, repo_root=ROOT)
        self.assertEqual(regenerated, self.fsir_suite)

    def test_empty_plan_intent_distinguishes_no_action_from_underspecified(self):
        no_action = FsirDocument(
            **self.fsir_by_name["soft_recommendation_no_executable_action"]["fsir"]
        )
        underspecified = FsirDocument(
            **self.fsir_by_name["missing_amount_instruction_is_omitted"]["fsir"]
        )

        self.assertEqual(no_action.meta.intent, "no_action")
        self.assertEqual(no_action.actions, [])
        self.assertFalse(
            any(item.severity == "blocking" for item in no_action.unresolved)
        )
        self.assertEqual(underspecified.meta.intent, "underspecified_action")
        self.assertEqual(underspecified.actions, [])
        self.assertTrue(
            any(item.severity == "blocking" for item in underspecified.unresolved)
        )

    def test_empty_no_action_plan_needs_no_synthetic_accounts(self):
        document = legacy_to_fsir(
            {"actions": []},
            source_text="No executable action is requested.",
            case_id="no_action_without_accounts",
            policy={"budget": 0, "account_balances": {}},
        )

        self.assertEqual(document.meta.intent, "no_action")
        self.assertEqual(document.state, [])
        self.assertEqual(
            [item.id for item in document.properties],
            ["property.no_action_without_accounts.type_ok"],
        )

    def test_underspecified_intent_without_blocking_question_is_rejected(self):
        raw = copy.deepcopy(
            self.fsir_by_name["soft_recommendation_no_executable_action"]["fsir"]
        )
        raw["meta"]["intent"] = "underspecified_action"
        with self.assertRaisesRegex(ValidationError, "blocking unresolved"):
            FsirDocument(**raw)

    def test_no_action_with_blocking_question_is_rejected(self):
        raw = copy.deepcopy(
            self.fsir_by_name["soft_recommendation_no_executable_action"]["fsir"]
        )
        raw["unresolved"] = [
            {
                "id": "unresolved.no_action.amount",
                "kind": "missing_value",
                "severity": "blocking",
                "blocks": [],
                "question": "What amount?",
                "source_span_ids": [
                    raw["provenance"]["spans"][0]["id"],
                ],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "no_action requires"):
            FsirDocument(**raw)

    def test_buy_debits_cash_and_credits_distinct_asset_position(self):
        document = FsirDocument(
            **self.fsir_by_name[
                "buy_inside_account_uses_account_as_source_and_destination"
            ]["fsir"]
        )
        self.assertEqual(
            [variable.id for variable in document.state if variable.type.kind == "asset_notional"],
            ["state.position.brokerage.vti"],
        )
        buy = document.actions[0]
        updates = [(update.op, update.target_state_id) for update in buy.updates]
        self.assertIn(("sub", "state.cash.brokerage"), updates)
        self.assertIn(("add", "state.position.brokerage.vti"), updates)
        self.assertNotIn(("add", "state.cash.brokerage"), updates)

    def test_unknown_fields_are_rejected_at_document_and_action_layers(self):
        raw = copy.deepcopy(
            self.fsir_by_name[
                "buy_inside_account_uses_account_as_source_and_destination"
            ]["fsir"]
        )
        raw["raw_tla"] = "arbitrary backend code"
        with self.assertRaises(ValidationError):
            FsirDocument(**raw)

        raw = copy.deepcopy(
            self.fsir_by_name[
                "buy_inside_account_uses_account_as_source_and_destination"
            ]["fsir"]
        )
        raw["actions"][0]["python"] = "balances.clear()"
        with self.assertRaises(ValidationError):
            FsirDocument(**raw)

    def test_undeclared_action_actor_is_rejected(self):
        raw = copy.deepcopy(
            self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        )
        raw["actions"][0]["actor_id"] = "service.missing"
        with self.assertRaisesRegex(ValidationError, "undeclared actor"):
            FsirDocument(**raw)

    def test_typed_account_parameters_must_reference_declared_symbols(self):
        raw = copy.deepcopy(
            self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        )
        source_parameter = next(
            parameter
            for parameter in raw["actions"][0]["parameters"]
            if parameter["name"] == "source"
        )
        self.assertTrue(source_parameter["value"].startswith("account."))
        source_parameter["value"] = "account.missing"
        with self.assertRaisesRegex(ValidationError, "unknown account"):
            FsirDocument(**raw)

    def test_source_hash_and_budget_semantics_are_explicit(self):
        for migrated in self.fsir_suite["cases"]:
            with self.subTest(case=migrated["name"]):
                meta = migrated["fsir"]["meta"]
                self.assertRegex(meta["source_document_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotEqual(meta["source_document_sha256"], "prototype")
                self.assertEqual(meta["budget_semantics"], "gross_debit")

    def test_legacy_choices_are_a_lossless_fsir_compatibility_subset(self):
        raw = {
            "choices": [
                {
                    "name": "fund first",
                    "actions": [
                        {
                            "action": "transfer",
                            "amount": 300,
                            "from": "checking",
                            "to": "brokerage",
                        },
                        {
                            "action": "transfer",
                            "amount": 100,
                            "from": "brokerage",
                            "to": "savings",
                        }
                    ],
                },
                {
                    "name": "save instead",
                    "actions": [
                        {
                            "action": "transfer",
                            "amount": 300,
                            "from": "checking",
                            "to": "savings",
                        }
                    ],
                },
            ]
        }
        policy = {
            "budget": 600,
            "account_balances": {"checking": 600, "brokerage": 0, "savings": 0},
        }
        document = legacy_to_fsir(
            raw,
            source_text="Either fund brokerage or save instead.",
            case_id="choice_round_trip",
            policy=policy,
        )
        self.assertEqual(document.control.kind, "choice")
        self.assertEqual(len(document.control.branches), 2)
        self.assertEqual(
            len(document.control.branches[0].action_ids),
            2,
        )
        self.assertIn(
            (
                document.control.branches[0].action_ids[0],
                document.control.branches[0].action_ids[1],
            ),
            {(edge.before, edge.after) for edge in document.control.edges},
        )
        self.assertEqual(fsir_to_legacy(document), raw)

    def test_control_must_cover_all_actions_and_remain_acyclic(self):
        raw = copy.deepcopy(
            self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        )
        raw["control"]["nodes"] = raw["control"]["nodes"][:1]
        raw["control"]["edges"] = []
        with self.assertRaisesRegex(ValidationError, "control must cover"):
            FsirDocument(**raw)

        raw = copy.deepcopy(
            self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        )
        raw["control"]["edges"].append(
            {
                "before": raw["control"]["nodes"][1],
                "after": raw["control"]["nodes"][0],
            }
        )
        with self.assertRaisesRegex(ValidationError, "acyclic"):
            FsirDocument(**raw)

    def test_closed_expression_rejects_backend_snippet_and_invalid_shape(self):
        raw = copy.deepcopy(
            self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        )
        raw["properties"][0]["formula"] = {
            "op": "state_ref",
            "state_id": "state.cash.checking",
            "value": 7,
            "value_type": "integer",
        }
        with self.assertRaisesRegex(ValidationError, "does not allow fields"):
            FsirDocument(**raw)

    def test_generated_json_schema_is_closed_at_top_level(self):
        schema = fsir_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "meta",
                "symbols",
                "state",
                "actions",
                "control",
                "properties",
                "assumptions",
                "bounds",
                "unresolved",
                "provenance",
                "compatibility",
            },
        )

    def test_checked_in_schema_matches_pydantic_generation(self):
        checked_in = load_json(ROOT / "docs" / "fsir-v0.1.schema.json")
        self.assertEqual(checked_in, fsir_json_schema())

    def test_dumped_fsir_revalidates_without_information_loss(self):
        raw = self.fsir_by_name["safe_transfer_then_buy_order_sensitive"]["fsir"]
        document = FsirDocument(**raw)
        dumped = dump_fsir(document)
        self.assertEqual(dump_fsir(FsirDocument(**dumped)), dumped)


if __name__ == "__main__":
    unittest.main()
