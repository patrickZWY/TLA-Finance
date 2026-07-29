import copy
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safety.fsir import FsirDocument, legacy_to_fsir
from safety.fsir_lowering import (
    TlcClassification,
    UnsupportedFsirError,
    build_execution_evidence_manifest,
    classify_tlc_result,
    lower_fsir,
    normalize_tlc_counterexample,
    verify_execution_evidence,
    verify_lowered_fsir,
    write_lowered_fsir,
)


ROOT = Path(__file__).resolve().parents[1]
FSIR_CASES = json.loads(
    (ROOT / "fixtures" / "fsir" / "semantic_codex_cases.fsir.json").read_text(
        encoding="utf-8"
    )
)
TLA_TOOLS_JAR = (
    ROOT.parent / "tla-finance-phase1" / "tools" / "tla2tools.jar"
)


def seed_document(name):
    raw = next(case["fsir"] for case in FSIR_CASES["cases"] if case["name"] == name)
    return FsirDocument(**raw)


def lifecycle_document(control_kind):
    raw = copy.deepcopy(
        next(
            case["fsir"]
            for case in FSIR_CASES["cases"]
            if case["name"] == "safe_transfer_then_buy_order_sensitive"
        )
    )
    span_id = raw["meta"]["source_document_span_id"]

    def replace_id(value, old, new):
        if isinstance(value, dict):
            return {
                key: replace_id(item, old, new)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace_id(item, old, new) for item in value]
        return new if value == old else value

    original_transfer_id = raw["actions"][0]["id"]
    original_buy_id = raw["actions"][1]["id"]
    raw = replace_id(
        raw,
        original_transfer_id,
        "event.transfer.settle",
    )
    raw = replace_id(
        raw,
        original_buy_id,
        "event.buy.execute",
    )
    transfer, buy = raw["actions"]
    transfer_id, buy_id = transfer["id"], buy["id"]

    def literal(value, value_type):
        result = {
            "op": "literal",
            "value": value,
            "value_type": value_type,
        }
        return result

    def event(event_id, status_id, value, actor):
        return {
            "id": event_id,
            "intent_id": event_id.replace("event.", "intent."),
            "kind": "environment_outcome" if value in {"settled", "filled"} else "submit",
            "actor_id": actor,
            "parameters": [],
            "guard": literal(True, "boolean"),
            "updates": [
                {
                    "op": "set",
                    "target_state_id": status_id,
                    "value": literal(value, "enum"),
                }
            ],
            "outcomes": [],
            "reads": [],
            "writes": [status_id],
            "atomicity_group": event_id.replace("event.", "atomic."),
            "source_span_ids": [span_id],
        }

    raw["state"].extend(
        [
            {
                "id": "state.transfer.status",
                "type": {
                    "kind": "enum",
                    "values": ["not_submitted", "pending", "settled"],
                },
                "initial": "not_submitted",
                "observable": True,
                "source_span_ids": [span_id],
            },
            {
                "id": "state.buy.status",
                "type": {
                    "kind": "enum",
                    "values": ["not_submitted", "submitted", "filled"],
                },
                "initial": "not_submitted",
                "observable": True,
                "source_span_ids": [span_id],
            },
        ]
    )
    buy_submit = event(
        "event.buy.submit",
        "state.buy.status",
        "submitted",
        "service.brokerage",
    )
    buy_submit["guard"] = {
        "op": "and",
        "args": [
            {
                "op": "gte",
                "left": {
                    "op": "state_ref",
                    "state_id": "state.cash.brokerage",
                },
                "right": literal(0, "money") | {"unit": "USD"},
            },
            {
                "op": "gte",
                "left": {
                    "op": "state_ref",
                    "state_id": "state.position.brokerage.vti",
                },
                "right": literal(0, "asset_notional")
                | {"unit": "USD_notional"},
            },
        ],
    }
    buy_submit["reads"] = [
        "state.cash.brokerage",
        "state.position.brokerage.vti",
    ]
    actions = [
        event(
            "event.transfer.submit",
            "state.transfer.status",
            "pending",
            "service.transfer",
        ),
        transfer,
        event(
            "event.transfer.settled",
            "state.transfer.status",
            "settled",
            "service.transfer",
        ),
        buy_submit,
        buy,
        event(
            "event.buy.filled",
            "state.buy.status",
            "filled",
            "service.brokerage",
        ),
    ]
    raw["actions"] = actions
    action_ids = [action["id"] for action in actions]
    if control_kind == "sequence":
        edges = [
            {"before": action_ids[index], "after": action_ids[index + 1]}
            for index in range(len(action_ids) - 1)
        ]
    else:
        edges = [
            {"before": action_ids[0], "after": action_ids[1]},
            {"before": action_ids[1], "after": action_ids[2]},
            {"before": action_ids[3], "after": action_ids[4]},
            {"before": action_ids[4], "after": action_ids[5]},
        ]
    raw["control"] = {
        "kind": control_kind,
        "nodes": action_ids,
        "edges": edges,
        "branches": [],
    }
    raw["bounds"]["max_actions"] = len(actions)
    raw["bounds"]["max_steps"] = len(actions)
    raw["assumptions"] = [
        {
            "id": "assumption.lifecycle.weak_fairness",
            "kind": "weak_fairness",
            "action_ids": action_ids,
            "source_span_ids": [span_id],
        }
    ]
    raw["properties"].extend(
        [
            {
                "id": "property.lifecycle.transfer_settles",
                "kind": "liveness",
                "formula": {
                    "op": "eventually",
                    "args": [
                        {
                            "op": "eq",
                            "left": {
                                "op": "state_ref",
                                "state_id": "state.transfer.status",
                            },
                            "right": literal("settled", "enum"),
                        }
                    ],
                },
                "severity": "error",
                "source_span_ids": [span_id],
            },
            {
                "id": "property.lifecycle.buy_fills",
                "kind": "liveness",
                "formula": {
                    "op": "eventually",
                    "args": [
                        {
                            "op": "eq",
                            "left": {
                                "op": "state_ref",
                                "state_id": "state.buy.status",
                            },
                            "right": literal("filled", "enum"),
                        }
                    ],
                },
                "severity": "error",
                "source_span_ids": [span_id],
            },
        ]
    )
    return FsirDocument(**raw)


def impossible_liveness_document():
    document = lifecycle_document("sequence")
    raw = document.model_dump(by_alias=True, exclude_none=True)
    buy_status = next(
        state
        for state in raw["state"]
        if state["id"] == "state.buy.status"
    )
    buy_status["type"]["values"].append("cancelled")
    raw["properties"] = [
        prop for prop in raw["properties"] if prop["kind"] != "liveness"
    ]
    raw["properties"].append(
        {
            "id": "property.lifecycle.buy_cancelled",
            "kind": "liveness",
            "formula": {
                "op": "eventually",
                "args": [
                    {
                        "op": "eq",
                        "left": {
                            "op": "state_ref",
                            "state_id": "state.buy.status",
                        },
                        "right": {
                            "op": "literal",
                            "value": "cancelled",
                            "value_type": "enum",
                        },
                    }
                ],
            },
            "severity": "error",
            "source_span_ids": [
                raw["meta"]["source_document_span_id"]
            ],
        }
    )
    return FsirDocument(**raw)


def run_tlc(lowered):
    with tempfile.TemporaryDirectory() as directory:
        paths = write_lowered_fsir(lowered, Path(directory))
        return subprocess.run(
            [
                "java",
                "-cp",
                str(TLA_TOOLS_JAR),
                "tlc2.TLC",
                "-config",
                paths["cfg"].name,
                paths["tla"].name,
            ],
            cwd=directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


def synthetic_trace(lowered, event_id, *, include_observables=True, include_last=True):
    state_lines = []
    if include_observables:
        for entry in lowered.source_map["states"].values():
            if entry["observable"]:
                state_lines.append(f'/\\ {entry["tla_variable"]} = 0')
    first = ['/\\ lastEvent = "init"'] if include_last else []
    second = [f'/\\ lastEvent = "{event_id}"'] if include_last else []
    return "\n".join(
        [
            "State 1: <Initial predicate>",
            *first,
            *state_lines,
            "",
            "State 2: <Action>",
            *second,
            *state_lines,
            "",
        ]
    )


class FsirLoweringTests(unittest.TestCase):
    def test_fixed_sequence_lowering_is_deterministic_and_complete(self):
        document = seed_document("safe_transfer_then_buy_order_sensitive")
        first = lower_fsir(document, "Fsir Sequence")
        second = lower_fsir(document, "Fsir Sequence")
        self.assertEqual(first, second)
        self.assertEqual(
            len(first.source_map["operators"]),
            len(document.actions),
        )
        self.assertEqual(
            len(first.source_map["properties"]),
            len(document.properties),
        )
        verify_lowered_fsir(document, first)

    def test_cash_and_asset_guards_are_lowered_into_action_enablement(self):
        document = lifecycle_document("sequence")
        lowered = lower_fsir(document, "GuardedFinance")
        cash_name = lowered.source_map["states"]["state.cash.brokerage"][
            "tla_variable"
        ]
        asset_name = lowered.source_map["states"][
            "state.position.brokerage.vti"
        ]["tla_variable"]
        self.assertIn(f"({cash_name} >= 0)", lowered.tla_text)
        self.assertIn(f"({asset_name} >= 0)", lowered.tla_text)

    def test_mutually_exclusive_plans_choose_one_stable_branch(self):
        document = legacy_to_fsir(
            {
                "choices": [
                    {
                        "name": "fund brokerage",
                        "actions": [
                            {
                                "action": "transfer",
                                "amount": 100,
                                "from": "checking",
                                "to": "brokerage",
                            }
                        ],
                    },
                    {
                        "name": "save cash",
                        "actions": [
                            {
                                "action": "transfer",
                                "amount": 100,
                                "from": "checking",
                                "to": "savings",
                            }
                        ],
                    },
                ]
            },
            source_text="Either fund brokerage or save cash.",
            case_id="lowering_choice",
            policy={
                "budget": 100,
                "max_individual_action_amount": 100,
                "account_balances": {
                    "brokerage": 0,
                    "checking": 100,
                    "savings": 0,
                },
                "allowed_destination_accounts": ["brokerage", "savings"],
                "allowed_action_types": ["transfer"],
            },
        )
        lowered = lower_fsir(document, "FsirChoice")
        self.assertIn("selectedBranch \\in", lowered.tla_text)
        self.assertEqual(len(lowered.source_map["branches"]), 2)
        self.assertEqual(
            len(set(lowered.source_map["branches"])),
            2,
        )

    def test_blocking_or_ambiguous_input_fails_closed(self):
        raw = copy.deepcopy(
            next(
                case["fsir"]
                for case in FSIR_CASES["cases"]
                if case["name"] == "missing_amount_instruction_is_omitted"
            )
        )
        with self.assertRaisesRegex(UnsupportedFsirError, "blocking unresolved"):
            lower_fsir(FsirDocument(**raw), "Blocked")

    def test_unmapped_lifecycle_action_cannot_bypass_finance_policy(self):
        document = lifecycle_document("sequence")
        raw = (
            document.model_dump(by_alias=True, exclude_none=True)
            if hasattr(document, "model_dump")
            else document.dict(by_alias=True, exclude_none=True)
        )
        submit = next(
            action
            for action in raw["actions"]
            if action["id"] == "event.transfer.submit"
        )
        submit["updates"] = [
            {
                "op": "add",
                "target_state_id": "state.cash.checking",
                "value": {
                    "op": "literal",
                    "value": 1,
                    "value_type": "money",
                    "unit": "USD",
                },
            }
        ]
        submit["reads"] = ["state.cash.checking"]
        submit["writes"] = ["state.cash.checking"]
        mutated = FsirDocument(**raw)
        with self.assertRaisesRegex(
            UnsupportedFsirError, "writes financial state"
        ):
            lower_fsir(mutated, "PolicyBypass")

    def test_model_config_source_map_and_manifest_mutations_are_rejected(self):
        document = seed_document("safe_transfer_then_buy_order_sensitive")
        lowered = lower_fsir(document, "Integrity")
        mutants = [
            replace(lowered, tla_text=lowered.tla_text.replace(">= 0", ">= -1", 1)),
            replace(lowered, cfg_text=lowered.cfg_text.replace("INVARIANTS", "\\* INVARIANTS", 1)),
            replace(lowered, source_map={**lowered.source_map, "operators": {}}),
            replace(lowered, manifest={**lowered.manifest, "outputs": {}}),
        ]
        for mutant in mutants:
            with self.subTest():
                with self.assertRaisesRegex(ValueError, "integrity"):
                    verify_lowered_fsir(document, mutant)

    def test_property_formula_mutation_invalidates_prior_artifacts(self):
        original = lifecycle_document("sequence")
        lowered = lower_fsir(original, "PropertyIntegrity")
        raw = (
            original.model_dump(by_alias=True, exclude_none=True)
            if hasattr(original, "model_dump")
            else original.dict(by_alias=True, exclude_none=True)
        )
        liveness = next(
            prop
            for prop in raw["properties"]
            if prop["id"] == "property.lifecycle.buy_fills"
        )
        liveness["formula"]["args"][0]["right"]["value"] = "submitted"
        mutated = FsirDocument(**raw)
        with self.assertRaisesRegex(ValueError, "integrity"):
            verify_lowered_fsir(mutated, lowered)

    def test_normalized_counterexample_uses_source_map_ids(self):
        document = seed_document("safe_transfer_then_buy_order_sensitive")
        lowered = lower_fsir(document, "Trace")
        action_id = document.actions[0].id
        output = synthetic_trace(lowered, action_id)
        trace = normalize_tlc_counterexample(output, lowered.source_map)
        self.assertEqual(trace[0]["event_id"], action_id)
        self.assertIsNotNone(trace[0]["operator_id"])
        self.assertEqual(
            set(trace[0]["before"]),
            set(lowered.source_map["states"]),
        )

    def test_infrastructure_failure_cannot_satisfy_property_violation(self):
        lowered = lower_fsir(
            lifecycle_document("partial_order"),
            "Classification",
        )
        classification = classify_tlc_result(
            150,
            "Error: Cannot find source file for module MissingModule.",
            lowered.source_map,
        )
        self.assertEqual(classification.kind, "infrastructure_failure")
        self.assertEqual(classification.violated_property_ids, ())

        temporal_map = copy.deepcopy(lowered.source_map)
        temporal_map["properties"] = {
            generated_id: entry
            for generated_id, entry in temporal_map["properties"].items()
            if entry["fsir_property_id"]
            == "property.lifecycle.buy_fills"
        }
        temporal_output = (
            "Error: Temporal properties were violated.\n"
            "Error: The following behavior constitutes a counter-example:\n"
        )
        temporal = classify_tlc_result(13, temporal_output, temporal_map)
        self.assertEqual(temporal.kind, "temporal_violation")
        self.assertEqual(
            temporal.violated_property_ids,
            ("property.lifecycle.buy_fills",),
        )
        self.assertEqual(
            classify_tlc_result(12, temporal_output, temporal_map).kind,
            "infrastructure_failure",
        )
        self.assertEqual(
            classify_tlc_result(
                13,
                "Error: Temporal properties were violated.",
                temporal_map,
            ).kind,
            "infrastructure_failure",
        )
        self.assertEqual(
            classify_tlc_result(
                13,
                temporal_output
                + "Error: Cannot find source file for module MissingModule.\n",
                temporal_map,
            ).kind,
            "infrastructure_failure",
        )

    def test_unsupported_assumptions_and_fairness_formulas_fail_closed(self):
        document = lifecycle_document("sequence")
        raw = (
            document.model_dump(by_alias=True, exclude_none=True)
            if hasattr(document, "model_dump")
            else document.dict(by_alias=True, exclude_none=True)
        )
        environment_raw = copy.deepcopy(raw)
        environment_raw["assumptions"].append(
            {
                "id": "assumption.environment.false",
                "kind": "environment",
                "formula": {
                    "op": "literal",
                    "value": False,
                    "value_type": "boolean",
                },
                "action_ids": [],
                "source_span_ids": [
                    environment_raw["meta"]["source_document_span_id"]
                ],
            }
        )
        with self.assertRaisesRegex(
            UnsupportedFsirError, "unsupported assumption kind"
        ):
            lower_fsir(FsirDocument(**environment_raw), "Environment")

        fairness_raw = copy.deepcopy(raw)
        fairness_raw["assumptions"][0]["formula"] = {
            "op": "literal",
            "value": True,
            "value_type": "boolean",
        }
        with self.assertRaisesRegex(
            UnsupportedFsirError, "cannot carry a formula"
        ):
            lower_fsir(FsirDocument(**fairness_raw), "FairnessFormula")

    def test_action_and_outcome_event_ids_must_be_globally_unique(self):
        document = lifecycle_document("sequence")
        raw = (
            document.model_dump(by_alias=True, exclude_none=True)
            if hasattr(document, "model_dump")
            else document.dict(by_alias=True, exclude_none=True)
        )
        action = next(
            item
            for item in raw["actions"]
            if item["id"] == "event.transfer.submit"
        )
        original_update = action["updates"][0]
        action["kind"] = "conditional_outcome"
        action["updates"] = []
        action["outcomes"] = [
            {
                "id": "event.buy.submit",
                "guard": {
                    "op": "literal",
                    "value": True,
                    "value_type": "boolean",
                },
                "updates": [original_update],
                "source_span_ids": action["source_span_ids"],
            },
            {
                "id": "outcome.transfer.submit.fallback",
                "guard": {
                    "op": "literal",
                    "value": False,
                    "value_type": "boolean",
                },
                "updates": [original_update],
                "source_span_ids": action["source_span_ids"],
            },
        ]
        collision = FsirDocument(**raw)
        with self.assertRaisesRegex(
            UnsupportedFsirError, "globally unique"
        ):
            lower_fsir(collision, "Collision")

    def test_trace_normalization_rejects_unknown_missing_and_duplicate_identity(self):
        document = lifecycle_document("partial_order")
        lowered = lower_fsir(document, "StrictTrace")
        known_event = document.actions[0].id

        with self.assertRaisesRegex(ValueError, "unknown event"):
            normalize_tlc_counterexample(
                synthetic_trace(lowered, "event.unknown"),
                lowered.source_map,
            )
        with self.assertRaisesRegex(ValueError, "missing observable"):
            normalize_tlc_counterexample(
                synthetic_trace(
                    lowered,
                    known_event,
                    include_observables=False,
                ),
                lowered.source_map,
            )
        with self.assertRaisesRegex(ValueError, "missing lastEvent"):
            normalize_tlc_counterexample(
                synthetic_trace(
                    lowered,
                    known_event,
                    include_last=False,
                ),
                lowered.source_map,
            )

        duplicate_map = copy.deepcopy(lowered.source_map)
        operator_entries = list(duplicate_map["operators"].values())
        operator_entries[1]["fsir_action_id"] = operator_entries[0][
            "fsir_action_id"
        ]
        with self.assertRaisesRegex(ValueError, "duplicate event identity"):
            normalize_tlc_counterexample(
                synthetic_trace(lowered, known_event),
                duplicate_map,
            )

    def test_emitted_fairness_assumption_is_named_and_source_mapped(self):
        document = lifecycle_document("sequence")
        lowered = lower_fsir(document, "FairnessMap")
        assumption = document.assumptions[0]
        entries = lowered.source_map["assumptions"]
        self.assertEqual(len(entries), 1)
        generated_id, entry = next(iter(entries.items()))
        self.assertEqual(entry["fsir_assumption_id"], assumption.id)
        self.assertEqual(entry["source_span_ids"], assumption.source_span_ids)
        self.assertIn(f"{generated_id} ==", lowered.tla_text)
        self.assertIn(f"/\\ {generated_id}", lowered.tla_text)

    def test_execution_evidence_manifest_binds_every_artifact(self):
        document = lifecycle_document("partial_order")
        lowered = lower_fsir(document, "ExecutionIntegrity")
        output = synthetic_trace(lowered, document.actions[0].id)
        trace = normalize_tlc_counterexample(output, lowered.source_map)
        classification = TlcClassification(
            kind="property_violation",
            returncode=12,
            violated_property_ids=(
                "property.safe_transfer_then_buy_order_sensitive.no_negative_cash",
            ),
            detail="synthetic bound violation",
        )
        report = {
            "expected": "property_violation",
            "observed": "property_violation",
            "satisfied": True,
        }
        manifest = build_execution_evidence_manifest(
            lowered=lowered,
            tlc_output=output,
            normalized_trace=trace,
            classification=classification,
            execution_report=report,
        )
        verify_execution_evidence(
            lowered=lowered,
            tlc_output=output,
            normalized_trace=trace,
            classification=classification,
            execution_report=report,
            execution_manifest=manifest,
        )
        mutations = [
            {"tlc_output": output + "\nmutated"},
            {"normalized_trace": []},
            {
                "classification": TlcClassification(
                    kind="infrastructure_failure",
                    returncode=150,
                )
            },
            {"execution_report": {**report, "satisfied": False}},
            {
                "execution_manifest": {
                    **manifest,
                    "artifacts": {},
                }
            },
        ]
        defaults = {
            "lowered": lowered,
            "tlc_output": output,
            "normalized_trace": trace,
            "classification": classification,
            "execution_report": report,
            "execution_manifest": manifest,
        }
        for mutation in mutations:
            with self.subTest(mutation=next(iter(mutation))):
                with self.assertRaisesRegex(ValueError, "execution evidence"):
                    verify_execution_evidence(**{**defaults, **mutation})

    @unittest.skipUnless(TLA_TOOLS_JAR.is_file(), "tla2tools.jar is unavailable")
    def test_real_tlc_accepts_ordered_lifecycle(self):
        document = lifecycle_document("sequence")
        lowered = lower_fsir(
            document,
            "FsirLifecycleOrdered",
            tla_tools_jar=TLA_TOOLS_JAR,
        )
        completed = run_tlc(lowered)
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, output)
        self.assertIn("No error has been found", output)
        self.assertEqual(
            classify_tlc_result(
                completed.returncode,
                output,
                lowered.source_map,
            ).kind,
            "passed",
        )

    @unittest.skipUnless(TLA_TOOLS_JAR.is_file(), "tla2tools.jar is unavailable")
    def test_real_tlc_finds_concurrent_lifecycle_counterexample(self):
        document = lifecycle_document("partial_order")
        lowered = lower_fsir(
            document,
            "FsirLifecycleConcurrent",
            tla_tools_jar=TLA_TOOLS_JAR,
        )
        completed = run_tlc(lowered)
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Invariant", output)
        classification = classify_tlc_result(
            completed.returncode,
            output,
            lowered.source_map,
        )
        self.assertEqual(classification.kind, "property_violation")
        self.assertEqual(
            classification.violated_property_ids,
            (
                "property.safe_transfer_then_buy_order_sensitive.no_negative_cash",
            ),
        )
        trace = normalize_tlc_counterexample(output, lowered.source_map)
        self.assertTrue(trace, output)
        self.assertIn(document.actions[4].id, [step["event_id"] for step in trace])

    @unittest.skipUnless(TLA_TOOLS_JAR.is_file(), "tla2tools.jar is unavailable")
    def test_real_tlc_classifies_single_liveness_counterexample(self):
        document = impossible_liveness_document()
        lowered = lower_fsir(
            document,
            "FsirLifecycleTemporal",
            tla_tools_jar=TLA_TOOLS_JAR,
        )
        completed = run_tlc(lowered)
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 13, output)
        classification = classify_tlc_result(
            completed.returncode,
            output,
            lowered.source_map,
        )
        self.assertEqual(classification.kind, "temporal_violation")
        self.assertEqual(
            classification.violated_property_ids,
            ("property.lifecycle.buy_cancelled",),
        )
        trace = normalize_tlc_counterexample(output, lowered.source_map)
        self.assertEqual(len(trace), 6, output)
        self.assertEqual(
            [step["event_id"] for step in trace],
            [action.id for action in document.actions],
        )
        report = {
            "expected": "temporal_violation",
            "observed": classification.kind,
            "property_ids": list(classification.violated_property_ids),
            "trace_steps": len(trace),
            "satisfied": True,
        }
        manifest = build_execution_evidence_manifest(
            lowered=lowered,
            tlc_output=output,
            normalized_trace=trace,
            classification=classification,
            execution_report=report,
        )
        verify_execution_evidence(
            lowered=lowered,
            tlc_output=output,
            normalized_trace=trace,
            classification=classification,
            execution_report=report,
            execution_manifest=manifest,
        )
        with self.assertRaisesRegex(ValueError, "execution evidence"):
            verify_execution_evidence(
                lowered=lowered,
                tlc_output=output + "\nmutated",
                normalized_trace=trace,
                classification=classification,
                execution_report=report,
                execution_manifest=manifest,
            )


if __name__ == "__main__":
    unittest.main()
