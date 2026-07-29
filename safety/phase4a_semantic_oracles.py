"""Closed Phase 4A semantic projection oracles and lower mappings.

This module is deliberately independent from the mutation patch registry.
Mutation code changes candidates; these rules decide whether a candidate still
matches the frozen semantic contract.  The lower mappings start from the
case-declared baseline fixture and derive the executable mutant from the full
mutated projection.  They never select a target fixture.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


SEMANTIC_ORACLE_VERSION = "phase4a-closed-semantic-oracle-0.2"
LOWER_MAPPING_VERSION = "phase4a-projection-fsir-mapping-0.2"
_MISSING = object()
_MASK = "__phase4a_mutation_field__"


class SemanticOracleViolation(ValueError):
    """A mutated projection violated a closed semantic gate."""

    def __init__(
        self,
        gate_code: str,
        changed_paths: list[str],
        *,
        message: str | None = None,
    ):
        self.gate_code = gate_code
        self.changed_paths = tuple(changed_paths)
        detail = message or (
            f"semantic gate {gate_code} rejected changed projection paths: "
            + ", ".join(changed_paths)
        )
        super().__init__(detail)

    def to_json(self) -> dict[str, Any]:
        return {
            "class": self.__class__.__name__,
            "gate_code": self.gate_code,
            "message": str(self),
            "changed_paths": list(self.changed_paths),
        }


# These rules are the executable semantic oracle. They intentionally duplicate
# no patch values: each rule protects the frozen field(s) whose semantic drift
# the corpus says must be rejected.
ORACLE_RULES: dict[str, dict[str, Any]] = {
    "mutant.01.amount": {
        "gate": "provenance_action_or_negative_balance",
        "paths": [
            "expected_semantics.actions.0.amount",
            "expected_semantics.actions.0.guard",
            "expected_semantics.actions.0.effects",
        ],
    },
    "mutant.02.destination": {
        "gate": "source_span_fsir_mismatch",
        "paths": [
            "expected_semantics.actions.0.to",
            "expected_semantics.actions.0.effects",
        ],
    },
    "mutant.03.net": {
        "gate": "canonical_policy_formula_binding",
        "paths": ["expected_semantics.properties.0.formula_label"],
    },
    "mutant.04.operator": {
        "gate": "canonical_formula_binding",
        "paths": ["expected_semantics.properties.0.formula_label"],
    },
    "mutant.05.zero": {
        "gate": "policy_state_provenance",
        "paths": ["candidate_initials.account.travel"],
    },
    "mutant.06.action": {
        "gate": "no_action_intent",
        "paths": [
            "expected_semantics.actions",
            "expected_semantics.control",
        ],
    },
    "mutant.07.omit": {
        "gate": "intent_classification",
        "paths": [
            "expected_semantics.actions",
            "expected_semantics.control",
        ],
    },
    "mutant.08.hide": {
        "gate": "source_action_coverage",
        "paths": ["expected_semantics.actions"],
    },
    "mutant.09.recredit": {
        "gate": "effect_state_type_or_conservation",
        "paths": ["expected_semantics.actions.1.effects.1"],
    },
    "mutant.10.final-only": {
        "gate": "intermediate_invariant_trace",
        "paths": ["expected_semantics.properties.0.formula_label"],
    },
    "mutant.11.flatten": {
        "gate": "control_topology",
        "paths": ["expected_semantics.control"],
    },
    "mutant.12.assume-sequence": {
        "gate": "unapproved_ambiguity_assumption",
        "paths": ["expected_semantics.control"],
    },
    "mutant.13.ignore-fee": {
        "gate": "scenario_coverage",
        "paths": ["expected_semantics.actions"],
    },
    "mutant.14.recredit": {
        "gate": "cash_asset_conservation",
        "paths": [
            "expected_semantics.actions.0.effects.1",
            "expected_semantics.actions.1.effects.1",
        ],
    },
    "mutant.15.recency": {
        "gate": "unresolved_policy_conflict",
        "paths": ["selected_policy_budget"],
    },
    "mutant.16.noop": {
        "gate": "unknown_action_noop",
        "paths": ["accepted_unknown_action_noop"],
    },
    "mutant.19.metadata-only": {
        "gate": "retry_bound_trace",
        "paths": ["expected_semantics.actions.1.guard"],
    },
    "mutant.20.no-seen": {
        "gate": "idempotent_debit_trace",
        "paths": [
            "expected_semantics.actions.0.guard",
            "expected_semantics.actions.0.effects",
        ],
    },
    "mutant.21.domain": {
        "gate": "bound_preservation",
        "paths": ["bounds.amount_domain"],
    },
    "mutant.22.infinite": {
        "gate": "external_source_conservation",
        "paths": ["expected_semantics.actions.0.effects"],
    },
    "mutant.23.repeat": {
        "gate": "single_refund_trace",
        "paths": ["expected_semantics.actions.1.guard"],
    },
    "mutant.24.split-check": {
        "gate": "atomic_budget_reservation",
        "paths": ["materializer_annotations.atomic_budget_update"],
    },
    "mutant.25.hide-fairness": {
        "gate": "fairness_provenance",
        "paths": [
            "expected_semantics.assumption_ids",
            "materializer_annotations.hidden_backend_assumptions",
        ],
    },
    "mutant.26.assume": {
        "gate": "unapproved_assumption",
        "paths": ["expected_semantics.assumption_ids"],
    },
    "mutant.27.global": {
        "gate": "property_strength",
        "paths": ["expected_semantics.properties.0.formula_label"],
    },
    "mutant.28.four": {
        "gate": "bounded_response_trace",
        "paths": [
            "expected_semantics.actions.0.guard",
            "bounds.time_horizon",
        ],
    },
    "mutant.29.guard": {
        "gate": "cancel_precedence_trace",
        "paths": ["expected_semantics.actions.1.guard"],
    },
    "mutant.30.assume-order": {
        "gate": "unapproved_ambiguity_assumption",
        "paths": ["expected_semantics.control"],
    },
    "mutant.30.weaken": {
        "gate": "property_preservation",
        "paths": ["expected_semantics.properties"],
    },
    "mutant.30.bound": {
        "gate": "bound_preservation",
        "paths": ["bounds.max_steps"],
    },
}


LOWER_MAPPING_SPECS: dict[str, dict[str, Any]] = {
    "mutant.17.submitted-is-settled": {
        "case_id": "core.17",
        "base_fixture_id": "fixture.phase3a.lifecycle.ordered",
        "projection_delta_paths": [
            "expected_semantics.actions.2.guard",
        ],
        "trigger_path": "expected_semantics.actions.2.guard",
        "trigger_value": (
            "pending.transfer1 = submitted and cash.brokerage >= 0"
        ),
        "base_control": "sequence",
        "target_control": "partial_order",
        "mapping_rule": (
            "submitted-status buy enablement removes the settlement-to-buy "
            "cross-chain dependency"
        ),
        "state_map": {
            "state.cash.checking": "state.cash.checking",
            "state.cash.brokerage": "state.cash.brokerage",
            "state.pending.transfer1": "state.transfer.status",
            "state.position.brokerage.VTI": (
                "state.position.brokerage.vti"
            ),
        },
        "assumption_map": {
            "assumption.bank-may-settle": (
                "assumption.lifecycle.weak_fairness"
            )
        },
    },
    "mutant.18.single-trace": {
        "case_id": "core.18",
        "base_fixture_id": "fixture.phase3a.lifecycle.concurrent",
        "projection_delta_paths": ["expected_semantics.control"],
        "trigger_path": "expected_semantics.control",
        "trigger_value": "sequence",
        "base_control": "partial_order",
        "target_control": "sequence",
        "mapping_rule": (
            "single settlement-first schedule replaces independent lifecycle "
            "chains with one total order"
        ),
        "state_map": {
            "state.cash.checking": "state.cash.checking",
            "state.cash.brokerage": "state.cash.brokerage",
            "state.pending.transfer1": "state.transfer.status",
            "state.order.buy1": "state.buy.status",
        },
        "assumption_map": {
            "assumption.environment-interleaving": (
                "assumption.lifecycle.weak_fairness"
            )
        },
    },
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def tool_identity() -> dict[str, str]:
    source = Path(__file__)
    return {
        "identity": SEMANTIC_ORACLE_VERSION,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def mapping_tool_identity() -> dict[str, str]:
    source = Path(__file__)
    return {
        "identity": LOWER_MAPPING_VERSION,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def _parts(path: str) -> list[str]:
    return path.split(".")


def value_at(document: Any, path: str) -> Any:
    current = document
    for part in _parts(path):
        if isinstance(current, list):
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            return _MISSING
    return current


def _set_mask(document: Any, path: str) -> None:
    parts = _parts(path)
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            if part not in current:
                current[part] = {}
            current = current[part]
    last = parts[-1]
    if isinstance(current, list):
        index = int(last)
        if index < len(current):
            current[index] = _MASK
        else:
            current.append(_MASK)
    else:
        current[last] = _MASK


def masked_projection(
    document: dict[str, Any], paths: list[str]
) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for path in paths:
        _set_mask(result, path)
    return result


def validate_semantic_projection(
    mutant_id: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Run the independent closed semantic gate for one non-lower mutant."""

    rule = ORACLE_RULES.get(mutant_id)
    if rule is None:
        raise KeyError(f"no closed semantic oracle for {mutant_id}")
    changed = [
        path
        for path in rule["paths"]
        if value_at(baseline, path) != value_at(candidate, path)
    ]
    if changed:
        raise SemanticOracleViolation(rule["gate"], changed)
    if baseline != candidate:
        raise SemanticOracleViolation(
            "closed_contract_drift",
            ["<unapproved-projection-field>"],
            message=(
                "closed semantic contract rejected projection drift outside "
                f"the declared {mutant_id} gate"
            ),
        )


def _fixture_directory(corpus_dir: Path, fixture_id: str) -> Path:
    suffix = fixture_id.rsplit(".", 1)[-1]
    if suffix not in {"ordered", "concurrent"}:
        raise ValueError(f"unknown lower fixture: {fixture_id}")
    return corpus_dir / "backend-artifacts" / suffix


def _sequence_edges(action_ids: list[str]) -> list[dict[str, str]]:
    return [
        {"before": action_ids[index], "after": action_ids[index + 1]}
        for index in range(len(action_ids) - 1)
    ]


def _independent_chain_edges(action_ids: list[str]) -> list[dict[str, str]]:
    if len(action_ids) != 6:
        raise ValueError("lifecycle mapping requires exactly six FSIR events")
    return [
        {"before": action_ids[0], "after": action_ids[1]},
        {"before": action_ids[1], "after": action_ids[2]},
        {"before": action_ids[3], "after": action_ids[4]},
        {"before": action_ids[4], "after": action_ids[5]},
    ]


def _replace_value(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_value(item, old, new)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_value(item, old, new) for item in value]
    return new if value == old else value


def _materialize_case_baseline(
    *,
    case: dict[str, Any],
    projection: dict[str, Any],
    fixture_input: dict[str, Any],
    mutant_id: str,
) -> dict[str, Any]:
    result = copy.deepcopy(fixture_input)
    old_span = result["meta"]["source_document_span_id"]
    new_span = case["source_spans"][0]["id"]
    result = _replace_value(result, old_span, new_span)
    stated_span = next(
        span
        for span in result["provenance"]["spans"]
        if span["id"] == new_span
    )
    old_source = stated_span["source_id"]
    new_source = f"source.phase4a.{case['id'].replace('.', '')}"
    result["provenance"]["sources"] = [
        new_source if source == old_source else source
        for source in result["provenance"]["sources"]
    ]
    stated_span.update(
        {
            "source_id": new_source,
            "start": 0,
            "end": len(case["prose"]),
            "text": case["prose"],
            "origin": "stated",
        }
    )
    result["meta"]["created_by"] = {
        "name": "tla-finance-phase4a-materializer",
        "version": "0.2",
    }
    result["meta"]["source_document_sha256"] = hashlib.sha256(
        case["prose"].encode("utf-8")
    ).hexdigest()
    result["bounds"]["max_actions"] = len(result["actions"])
    result["bounds"]["max_steps"] = max(
        projection["bounds"]["max_steps"], len(result["actions"])
    )
    result["bounds"]["max_retries"] = projection["bounds"]["retry_limit"]
    # The approved bounded lowerer rejects non-zero time_horizon. Preserve its
    # exact executable zero and bind the research horizon in the mapping proof
    # as non-executable corpus metadata; do not silently claim time semantics.
    result["bounds"]["time_horizon"] = 0
    bound_values = set(projection["bounds"]["amount_domain"])
    bound_values.update(result["policy"]["initial_cash_by_account_id"].values())
    result["bounds"]["domains"][0]["values"] = sorted(bound_values)
    return result


def derive_lower_input(
    *,
    mutant_id: str,
    case: dict[str, Any],
    baseline_projection: dict[str, Any],
    mutated_projection: dict[str, Any],
    corpus_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive a lower mutant FSIR input and its total mapping proof."""

    spec = LOWER_MAPPING_SPECS.get(mutant_id)
    if spec is None:
        raise KeyError(f"no lower mapping for {mutant_id}")
    if case["id"] != spec["case_id"]:
        raise ValueError(f"lower mapping case mismatch for {mutant_id}")
    lowering = case["lowering_oracle"]
    if lowering["fixture_id"] != spec["base_fixture_id"]:
        raise ValueError(f"lower mapping base fixture drift for {mutant_id}")
    allowed_paths = spec["projection_delta_paths"]
    changed = [
        path
        for path in allowed_paths
        if value_at(baseline_projection, path)
        != value_at(mutated_projection, path)
    ]
    if changed != allowed_paths:
        raise ValueError(f"lower projection delta is incomplete for {mutant_id}")
    baseline_masked = masked_projection(baseline_projection, allowed_paths)
    mutated_masked = masked_projection(mutated_projection, allowed_paths)
    if baseline_masked != mutated_masked:
        raise ValueError(f"lower projection has unmapped drift for {mutant_id}")
    trigger = value_at(mutated_projection, spec["trigger_path"])
    if trigger != spec["trigger_value"]:
        raise ValueError(f"lower mapping trigger mismatch for {mutant_id}")

    fixture_dir = _fixture_directory(corpus_dir, spec["base_fixture_id"])
    fixture_input = json.loads(
        (fixture_dir / "input.fsir.json").read_text(encoding="utf-8")
    )
    if fixture_input["control"]["kind"] != spec["base_control"]:
        raise ValueError(f"base fixture control drift for {mutant_id}")
    baseline_input = _materialize_case_baseline(
        case=case,
        projection=baseline_projection,
        fixture_input=fixture_input,
        mutant_id=mutant_id,
    )
    semantic = baseline_projection["expected_semantics"]
    action_map = lowering["semantic_action_map"]
    property_map = lowering["semantic_property_map"]
    if set(action_map) != {
        action["id"] for action in semantic["actions"]
    }:
        raise ValueError(f"semantic action mapping is not total for {mutant_id}")
    mapped_action_ids = {
        action_id
        for action_ids in action_map.values()
        for action_id in action_ids
    }
    if mapped_action_ids != {
        action["id"] for action in baseline_input["actions"]
    }:
        raise ValueError(f"FSIR action mapping is not total for {mutant_id}")
    if set(property_map) != {
        prop["id"] for prop in semantic["properties"]
    }:
        raise ValueError(f"semantic property mapping is not total for {mutant_id}")
    if not set(property_map.values()).issubset(
        {prop["id"] for prop in baseline_input["properties"]}
    ):
        raise ValueError(f"FSIR property mapping is invalid for {mutant_id}")
    if set(spec["state_map"]) != set(semantic["state_ids"]):
        raise ValueError(f"semantic state mapping is not total for {mutant_id}")
    if not set(spec["state_map"].values()).issubset(
        {state["id"] for state in baseline_input["state"]}
    ):
        raise ValueError(f"FSIR state mapping is invalid for {mutant_id}")
    if set(spec["assumption_map"]) != set(semantic["assumption_ids"]):
        raise ValueError(
            f"semantic assumption mapping is not total for {mutant_id}"
        )
    if not set(spec["assumption_map"].values()).issubset(
        {item["id"] for item in baseline_input["assumptions"]}
    ):
        raise ValueError(f"FSIR assumption mapping is invalid for {mutant_id}")
    mutated_input = copy.deepcopy(baseline_input)
    action_ids = [action["id"] for action in mutated_input["actions"]]
    target = spec["target_control"]
    mutated_input["control"]["kind"] = target
    mutated_input["control"]["edges"] = (
        _sequence_edges(action_ids)
        if target == "sequence"
        else _independent_chain_edges(action_ids)
    )
    baseline_without_control = copy.deepcopy(baseline_input)
    mutated_without_control = copy.deepcopy(mutated_input)
    del baseline_without_control["control"]
    del mutated_without_control["control"]
    if baseline_without_control != mutated_without_control:
        raise AssertionError("lower mapping changed data outside FSIR control")
    if baseline_input["control"] == mutated_input["control"]:
        raise AssertionError("lower mapping produced no executable mutation")

    projection_delta = [
        {
            "path": path,
            "before_sha256": sha256_json(value_at(baseline_projection, path)),
            "after_sha256": sha256_json(value_at(mutated_projection, path)),
        }
        for path in allowed_paths
    ]
    executable_delta = [
        {
            "path": "control.kind",
            "before_sha256": sha256_json(
                baseline_input["control"]["kind"]
            ),
            "after_sha256": sha256_json(
                mutated_input["control"]["kind"]
            ),
        },
        {
            "path": "control.edges",
            "before_sha256": sha256_json(
                baseline_input["control"]["edges"]
            ),
            "after_sha256": sha256_json(
                mutated_input["control"]["edges"]
            ),
        },
    ]
    declared_mapping = {
        "schema_version": LOWER_MAPPING_VERSION,
        "mutant_id": mutant_id,
        "case_id": case["id"],
        "base_fixture_id": spec["base_fixture_id"],
        "mapping_rule": spec["mapping_rule"],
        "projection_delta_paths": allowed_paths,
        "executable_delta_paths": ["control.kind", "control.edges"],
        "semantic_action_map": lowering["semantic_action_map"],
        "semantic_property_map": lowering["semantic_property_map"],
        "semantic_state_map": spec["state_map"],
        "semantic_assumption_map": spec["assumption_map"],
        "bounds_mapping": {
            "max_actions": "expanded lifecycle event count",
            "max_steps": "max(projection max_steps, lifecycle event count)",
            "max_retries": "projection retry_limit",
            "time_horizon": (
                "bound as non-executable research metadata; approved lowerer "
                "requires executable value zero"
            ),
            "amount_domain": (
                "union(projection amount_domain, policy initial cash values)"
            ),
        },
        "source_mapping": (
            "all executable source spans use the case source span; policy "
            "provenance remains policy-bound"
        ),
    }
    proof = {
        "schema_version": "phase4a-projection-fsir-proof-0.2",
        "mapping_tool": mapping_tool_identity(),
        "declared_mapping": declared_mapping,
        "declared_mapping_sha256": sha256_json(declared_mapping),
        "full_projection_binding": {
            "baseline_sha256": sha256_json(baseline_projection),
            "mutated_sha256": sha256_json(mutated_projection),
            "unchanged_projection_sha256": sha256_json(baseline_masked),
            "mutated_projection_masked_sha256": sha256_json(mutated_masked),
        },
        "projection_delta": projection_delta,
        "base_fixture_input_sha256": sha256_json(fixture_input),
        "mapped_baseline_input_sha256": sha256_json(baseline_input),
        "mutated_input_sha256": sha256_json(mutated_input),
        "executable_delta": executable_delta,
    }
    return mutated_input, proof
