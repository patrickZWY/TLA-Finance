"""Deterministic, fail-closed FSIR v0.1 to TLA+ lowering.

The lowerer deliberately supports a bounded and reviewable subset.  It emits
direct TLA+ (rather than PlusCal) so the generated text, operator identities,
source map, and hashes are stable inputs to TLC.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import safety.fsir as fsir_contract
from safety.fsir import (
    ActionOutcome,
    Expression,
    FsirAction,
    FsirDocument,
    Property,
    StateUpdate,
    dump_fsir,
)


LOWERER_VERSION = "fsir-tla-lowerer-0.1"
SOURCE_MAP_VERSION = "fsir-tla-source-map-0.1"
MANIFEST_VERSION = "fsir-tla-manifest-0.1"
EXECUTION_MANIFEST_VERSION = "fsir-tla-execution-evidence-0.1"


class UnsupportedFsirError(ValueError):
    """Raised when FSIR is valid but outside the explicitly supported subset."""


@dataclass(frozen=True)
class LoweredFsir:
    module_name: str
    tla_text: str
    cfg_text: str
    source_map: dict[str, Any]
    manifest: dict[str, Any]


TlcClassificationKind = Literal[
    "passed",
    "property_violation",
    "temporal_violation",
    "infrastructure_failure",
]


@dataclass(frozen=True)
class TlcClassification:
    kind: TlcClassificationKind
    returncode: int
    violated_property_ids: tuple[str, ...] = ()
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "returncode": self.returncode,
            "violated_property_ids": list(self.violated_property_ids),
            "detail": self.detail,
        }


def lower_fsir(
    document: FsirDocument,
    module_name: str,
    *,
    tla_tools_jar: Path | None = None,
) -> LoweredFsir:
    """Lower a validated FSIR document into deterministic TLA+ artifacts."""

    _validate_supported_subset(document)
    module = _module_name(module_name)
    state_names = {
        variable.id: _stable_name("State", variable.id)
        for variable in document.state
    }
    action_names: dict[tuple[str, str | None], str] = {}
    for action in document.actions:
        if action.kind == "conditional_outcome":
            for outcome in action.outcomes:
                action_names[(action.id, outcome.id)] = _stable_name(
                    "Act", f"{action.id}.{outcome.id}"
                )
        else:
            action_names[(action.id, None)] = _stable_name("Act", action.id)
    property_names = {
        prop.id: _stable_name("Prop", prop.id)
        for prop in document.properties
    }
    assumption_names = {
        assumption.id: _stable_name("Assume", assumption.id)
        for assumption in document.assumptions
    }
    branch_names = {
        branch.id: _stable_token("branch", branch.id)
        for branch in document.control.branches
    }
    _require_unique_generated_names(
        list(state_names.values()), "state variable"
    )
    _require_unique_generated_names(
        list(action_names.values()), "action operator"
    )
    _require_unique_generated_names(
        list(property_names.values()), "property operator"
    )
    _require_unique_generated_names(
        list(assumption_names.values()), "assumption operator"
    )
    _require_unique_generated_names(
        list(branch_names.values()), "branch token"
    )
    input_payload = _canonical_json(dump_fsir(document))

    source_map = _source_map(
        document,
        module,
        state_names,
        action_names,
        property_names,
        assumption_names,
        branch_names,
    )
    source_map_text = _canonical_json(source_map) + "\n"
    tla_text = _render_tla(
        document,
        module,
        state_names,
        action_names,
        property_names,
        assumption_names,
        branch_names,
    )
    cfg_text = _render_cfg(document, property_names)
    manifest = _manifest(
        document=document,
        module_name=module,
        input_payload=input_payload,
        tla_text=tla_text,
        cfg_text=cfg_text,
        source_map_text=source_map_text,
        tla_tools_jar=tla_tools_jar,
    )
    return LoweredFsir(
        module_name=module,
        tla_text=tla_text,
        cfg_text=cfg_text,
        source_map=source_map,
        manifest=manifest,
    )


def write_lowered_fsir(lowered: LoweredFsir, artifact_dir: Path) -> dict[str, Path]:
    """Write all lowering artifacts and return their paths."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "tla": artifact_dir / f"{lowered.module_name}.tla",
        "cfg": artifact_dir / f"{lowered.module_name}.cfg",
        "source_map": artifact_dir / "source-map.json",
        "manifest": artifact_dir / "manifest.json",
    }
    paths["tla"].write_text(lowered.tla_text, encoding="utf-8")
    paths["cfg"].write_text(lowered.cfg_text, encoding="utf-8")
    paths["source_map"].write_text(
        _canonical_json(lowered.source_map) + "\n", encoding="utf-8"
    )
    paths["manifest"].write_text(
        _canonical_json(lowered.manifest) + "\n", encoding="utf-8"
    )
    return paths


def verify_lowered_fsir(
    document: FsirDocument,
    lowered: LoweredFsir,
    *,
    tla_tools_jar: Path | None = None,
) -> None:
    """Reject any artifact or manifest drift from deterministic regeneration."""

    expected = lower_fsir(
        document,
        lowered.module_name,
        tla_tools_jar=tla_tools_jar,
    )
    comparisons = {
        "model": (lowered.tla_text, expected.tla_text),
        "config": (lowered.cfg_text, expected.cfg_text),
        "source map": (lowered.source_map, expected.source_map),
        "manifest": (lowered.manifest, expected.manifest),
    }
    drift = [label for label, (actual, wanted) in comparisons.items() if actual != wanted]
    if drift:
        raise ValueError(
            "lowered FSIR artifacts fail deterministic integrity: "
            + ", ".join(drift)
        )


def classify_tlc_result(
    returncode: int,
    output: str,
    source_map: dict[str, Any],
) -> TlcClassification:
    """Classify TLC evidence without conflating a tool failure and a violation."""

    if returncode == 0 and "No error has been found" in output:
        return TlcClassification(
            kind="passed",
            returncode=returncode,
            detail="TLC completed with no reported error",
        )

    property_map = source_map.get("properties")
    if not isinstance(property_map, dict):
        return TlcClassification(
            kind="infrastructure_failure",
            returncode=returncode,
            detail="source map has no property mapping",
        )
    invariant_matches = re.findall(
        r"^Error: Invariant ([A-Za-z][A-Za-z0-9_]*) is violated\.$",
        output,
        flags=re.MULTILINE,
    )
    if invariant_matches:
        if returncode != 12:
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="invariant text arrived with a non-violation exit code",
            )
        if len(invariant_matches) != 1:
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="TLC reported an ambiguous invariant set",
            )
        generated_id = invariant_matches[0]
        entry = property_map.get(generated_id)
        if not isinstance(entry, dict) or not entry.get("fsir_property_id"):
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail=f"violated invariant {generated_id} is absent from source map",
            )
        return TlcClassification(
            kind="property_violation",
            returncode=returncode,
            violated_property_ids=(str(entry["fsir_property_id"]),),
            detail=f"TLC violated invariant {generated_id}",
        )

    temporal_matches = re.findall(
        r"^Error: Temporal propert(?:y is|ies were) violated\.$",
        output,
        flags=re.MULTILINE,
    )
    if temporal_matches:
        if returncode != 13:
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="temporal-violation text arrived with a non-violation exit code",
            )
        if len(temporal_matches) != 1:
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="TLC reported an ambiguous temporal-violation set",
            )
        if not re.search(
            r"^Error: The following behavior constitutes a counter-example:$",
            output,
            flags=re.MULTILINE,
        ):
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="temporal violation has no TLC counterexample",
            )
        error_lines = re.findall(r"^Error: .+$", output, flags=re.MULTILINE)
        if len(error_lines) != 2:
            return TlcClassification(
                kind="infrastructure_failure",
                returncode=returncode,
                detail="temporal violation arrived with contradictory TLC errors",
            )
        temporal_ids = sorted(
            str(entry["fsir_property_id"])
            for entry in property_map.values()
            if isinstance(entry, dict)
            and entry.get("kind") == "liveness"
            and entry.get("fsir_property_id")
        )
        if len(temporal_ids) == 1:
            return TlcClassification(
                kind="temporal_violation",
                returncode=returncode,
                violated_property_ids=(temporal_ids[0],),
                detail="TLC reported the sole configured temporal property",
            )
        return TlcClassification(
            kind="infrastructure_failure",
            returncode=returncode,
            detail="temporal violation cannot be bound to exactly one property",
        )

    return TlcClassification(
        kind="infrastructure_failure",
        returncode=returncode,
        detail="TLC did not report a recognized bound property violation",
    )


def build_execution_evidence_manifest(
    *,
    lowered: LoweredFsir,
    tlc_output: str,
    normalized_trace: list[dict[str, Any]],
    classification: TlcClassification,
    execution_report: dict[str, Any],
) -> dict[str, Any]:
    """Integrity-bind lowering, raw execution, trace, classification, and report."""

    payloads = {
        "lowering_manifest": _canonical_json(lowered.manifest) + "\n",
        "tlc_output": tlc_output,
        "normalized_trace": _canonical_json(normalized_trace) + "\n",
        "classification": _canonical_json(classification.to_json()) + "\n",
        "execution_report": _canonical_json(execution_report) + "\n",
    }
    return {
        "schema_version": EXECUTION_MANIFEST_VERSION,
        "module_name": lowered.module_name,
        "hash_algorithm": "sha256",
        "artifacts": {
            name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in payloads.items()
        },
    }


def verify_execution_evidence(
    *,
    lowered: LoweredFsir,
    tlc_output: str,
    normalized_trace: list[dict[str, Any]],
    classification: TlcClassification,
    execution_report: dict[str, Any],
    execution_manifest: dict[str, Any],
) -> None:
    """Reject drift in any execution-evidence artifact."""

    expected = build_execution_evidence_manifest(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=normalized_trace,
        classification=classification,
        execution_report=execution_report,
    )
    if execution_manifest != expected:
        raise ValueError("execution evidence fails deterministic integrity")


def normalize_tlc_counterexample(
    output: str,
    source_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize TLC state output into stable FSIR event transitions.

    TLC prints one or more ``State N:`` blocks.  The generated model records
    the last FSIR action/outcome ID in ``lastEvent``; source-map lookup then
    attaches the stable generated operator ID.  Only observable FSIR state is
    included, and the result contains explicit before/after values.
    """

    states = _parse_tlc_states(output)
    if len(states) < 2:
        return []
    state_map = source_map["states"]
    operator_by_event: dict[str, str] = {}
    for operator_id, entry in source_map["operators"].items():
        event_id = entry.get("fsir_outcome_id") or entry["fsir_action_id"]
        if event_id in operator_by_event:
            raise ValueError(
                f"source map has duplicate event identity {event_id}"
            )
        operator_by_event[event_id] = operator_id

    normalized: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    for before, after in zip(states, states[1:]):
        if "lastEvent" not in before or "lastEvent" not in after:
            raise ValueError("TLC trace state is missing lastEvent")
        if before == after:
            continue
        event_id = str(after["lastEvent"])
        if not event_id or event_id == "init":
            raise ValueError("non-initial TLC transition has no event identity")
        if event_id not in operator_by_event:
            raise ValueError(f"TLC trace references unknown event {event_id}")
        if event_id in seen_events:
            raise ValueError(f"TLC trace repeats one-shot event {event_id}")
        seen_events.add(event_id)
        missing_values = sorted(
            entry["tla_variable"]
            for entry in state_map.values()
            if entry["observable"]
            and (
                entry["tla_variable"] not in before
                or entry["tla_variable"] not in after
            )
        )
        if missing_values:
            raise ValueError(
                "TLC trace is missing observable state values: "
                + ", ".join(missing_values)
            )
        before_values = {
            fsir_id: before[entry["tla_variable"]]
            for fsir_id, entry in state_map.items()
            if entry["observable"]
        }
        after_values = {
            fsir_id: after[entry["tla_variable"]]
            for fsir_id, entry in state_map.items()
            if entry["observable"]
        }
        normalized.append(
            {
                "step": len(normalized) + 1,
                "event_id": event_id,
                "operator_id": operator_by_event[event_id],
                "before": before_values,
                "after": after_values,
            }
        )
    return normalized


def _validate_supported_subset(document: FsirDocument) -> None:
    blocking = [item.id for item in document.unresolved if item.severity == "blocking"]
    if blocking:
        raise UnsupportedFsirError(
            "lowering refuses blocking unresolved items: " + ", ".join(blocking)
        )
    if document.meta.intent == "underspecified_action":
        raise UnsupportedFsirError("underspecified_action cannot be lowered")
    if document.control.kind in {"ambiguous", "parallel"}:
        raise UnsupportedFsirError(
            f"control kind {document.control.kind!r} is outside the bounded subset"
        )
    if document.actions and document.control.kind == "none":
        raise UnsupportedFsirError("actions require explicit control")
    supported_control = {"none", "sequence", "choice", "partial_order"}
    if document.control.kind not in supported_control:
        raise UnsupportedFsirError(
            f"unsupported control kind {document.control.kind!r}"
        )
    if document.bounds.max_retries != 0 or document.bounds.time_horizon != 0:
        raise UnsupportedFsirError(
            "retry and time-horizon semantics are not supported by this lowerer"
        )

    domain_by_id = {domain.id: domain for domain in document.bounds.domains}
    state_by_id = {variable.id: variable for variable in document.state}
    policy_action_ids = {
        item.fsir_action_id for item in document.compatibility.id_map
    }
    action_ids = {action.id for action in document.actions}
    outcome_ids = {
        outcome.id
        for action in document.actions
        for outcome in action.outcomes
    }
    colliding_event_ids = sorted(action_ids & outcome_ids)
    if colliding_event_ids:
        raise UnsupportedFsirError(
            "action and outcome event IDs must be globally unique: "
            + ", ".join(colliding_event_ids)
        )
    for variable in document.state:
        if variable.type.kind not in {
            "money",
            "asset_notional",
            "integer",
            "boolean",
            "enum",
        }:
            raise UnsupportedFsirError(
                f"unsupported state type {variable.type.kind!r} on {variable.id}"
            )
        if variable.initial_domain_bound_id is not None:
            domain = domain_by_id[variable.initial_domain_bound_id]
            if not domain.values:
                raise UnsupportedFsirError(
                    f"empty initial domain for {variable.id}"
                )

    for action in document.actions:
        if action.kind not in {
            "legacy_atomic",
            "submit",
            "environment_outcome",
            "conditional_outcome",
        }:
            raise UnsupportedFsirError(
                f"unsupported action kind {action.kind!r} on {action.id}"
            )
        _validate_state_updates(action.id, action.updates)
        _validate_action_expression(action.guard, f"guard of {action.id}")
        for update in action.updates:
            _validate_action_expression(
                update.value, f"update value in {action.id}"
            )
        for outcome in action.outcomes:
            _validate_state_updates(outcome.id, outcome.updates)
            _validate_action_expression(
                outcome.guard, f"guard of {outcome.id}"
            )
            for update in outcome.updates:
                _validate_action_expression(
                    update.value, f"update value in {outcome.id}"
                )
        if action.id not in policy_action_ids:
            lifecycle_targets = {
                update.target_state_id
                for update in action.updates
            } | {
                update.target_state_id
                for outcome in action.outcomes
                for update in outcome.updates
            }
            financial_targets = [
                state_id
                for state_id in sorted(lifecycle_targets)
                if state_by_id[state_id].type.kind
                in {"money", "asset_notional"}
            ]
            if financial_targets:
                raise UnsupportedFsirError(
                    f"unmapped lifecycle action {action.id} writes financial state: "
                    + ", ".join(financial_targets)
                )

    for prop in document.properties:
        _validate_property_expression(prop.formula, prop.id)

    for assumption in document.assumptions:
        if assumption.kind not in {"weak_fairness", "strong_fairness"}:
            raise UnsupportedFsirError(
                f"unsupported assumption kind {assumption.kind!r} "
                f"on {assumption.id}"
            )
        if assumption.formula is not None:
            raise UnsupportedFsirError(
                f"fairness assumption {assumption.id} cannot carry a formula "
                "in the bounded lowering subset"
            )


def _validate_state_updates(owner_id: str, updates: list[StateUpdate]) -> None:
    targets = [update.target_state_id for update in updates]
    if len(targets) != len(set(targets)):
        raise UnsupportedFsirError(
            f"{owner_id} updates a state variable more than once"
        )


def _walk_expression(expression: Expression) -> Iterable[Expression]:
    yield expression
    for child in expression.args:
        yield from _walk_expression(child)
    if expression.left is not None:
        yield from _walk_expression(expression.left)
    if expression.right is not None:
        yield from _walk_expression(expression.right)


def _validate_action_expression(expression: Expression, context: str) -> None:
    forbidden = {"always", "eventually", "precedence", "well_typed_state"}
    found = sorted({node.op for node in _walk_expression(expression)} & forbidden)
    if found:
        raise UnsupportedFsirError(
            f"{context} contains temporal/non-state operators: {', '.join(found)}"
        )


def _validate_property_expression(expression: Expression, property_id: str) -> None:
    for node in _walk_expression(expression):
        if node.op == "always" and node is not expression:
            raise UnsupportedFsirError(
                f"property {property_id} nests always outside the supported subset"
            )
        if node.op == "eventually" and node is not expression:
            raise UnsupportedFsirError(
                f"property {property_id} nests eventually outside the supported subset"
            )


def _render_tla(
    document: FsirDocument,
    module: str,
    state_names: dict[str, str],
    action_names: dict[tuple[str, str | None], str],
    property_names: dict[str, str],
    assumption_names: dict[str, str],
    branch_names: dict[str, str],
) -> str:
    state_vars = [state_names[item.id] for item in document.state]
    variables = state_vars + ["done", "selectedBranch", "lastEvent"]
    var_tuple = "vars == <<" + ", ".join(variables) + ">>"
    domain_by_id = {domain.id: domain for domain in document.bounds.domains}

    init_lines: list[str] = []
    for variable in document.state:
        tla_name = state_names[variable.id]
        if variable.initial_domain_bound_id is None:
            init_lines.append(f"/\\ {tla_name} = {_tla_value(variable.initial)}")
        else:
            values = domain_by_id[variable.initial_domain_bound_id].values
            init_lines.append(f"/\\ {tla_name} \\in {_tla_set(values)}")
    init_lines.append("/\\ done = {}")
    if document.control.kind == "choice":
        init_lines.append(
            "/\\ selectedBranch \\in "
            + _tla_set([branch_names[item.id] for item in document.control.branches])
        )
    else:
        init_lines.append('/\\ selectedBranch = "fixed"')
    init_lines.append('/\\ lastEvent = "init"')

    predecessors: dict[str, list[str]] = {
        action.id: [] for action in document.actions
    }
    for edge in document.control.edges:
        predecessors[edge.after].append(edge.before)
    branch_by_action = {
        action_id: branch_names[branch.id]
        for branch in document.control.branches
        for action_id in branch.action_ids
    }
    action_by_id = {action.id: action for action in document.actions}

    operator_blocks: list[str] = []
    operator_ids: list[str] = []
    for action in document.actions:
        if action.kind == "conditional_outcome":
            for outcome in action.outcomes:
                op_name = action_names[(action.id, outcome.id)]
                operator_ids.append(op_name)
                operator_blocks.append(
                    _render_action_operator(
                        action=action,
                        outcome=outcome,
                        op_name=op_name,
                        event_id=outcome.id,
                        state_names=state_names,
                        predecessors=predecessors[action.id],
                        selected_branch=branch_by_action.get(action.id),
                        all_state_vars=state_vars,
                        action_by_id=action_by_id,
                    )
                )
        else:
            op_name = action_names[(action.id, None)]
            operator_ids.append(op_name)
            operator_blocks.append(
                _render_action_operator(
                    action=action,
                    outcome=None,
                    op_name=op_name,
                    event_id=action.id,
                    state_names=state_names,
                    predecessors=predecessors[action.id],
                    selected_branch=branch_by_action.get(action.id),
                    all_state_vars=state_vars,
                    action_by_id=action_by_id,
                )
            )

    property_blocks = [
        f"{property_names[prop.id]} == "
        f"{_property_expression(prop, state_names, action_by_id)}"
        for prop in document.properties
    ]
    next_body = (
        "\n".join(f"  \\/ {operator_id}" for operator_id in operator_ids)
        if operator_ids
        else "  FALSE"
    )
    assumption_blocks, fairness = _render_assumptions(
        document,
        action_names,
        assumption_names,
    )
    sections = [
        f"---- MODULE {module} ----",
        "EXTENDS Integers, FiniteSets, Sequences",
        "",
        f"\\* Generated deterministically by {LOWERER_VERSION}.",
        "\\* FSIR IDs are retained in source-map.json and lastEvent.",
        "",
        "VARIABLES " + ", ".join(variables),
        var_tuple,
        "",
        "Init ==",
        "\n".join(f"  {line}" for line in init_lines),
        "",
    ]
    if operator_blocks:
        sections.extend(["\n\n".join(operator_blocks), ""])
    if assumption_blocks:
        sections.extend(["\n\n".join(assumption_blocks), ""])
    sections.extend(
        [
            "Next ==",
            next_body,
            "",
            "Spec == Init /\\ [][Next]_vars" + fairness,
            "",
        ]
    )
    if property_blocks:
        sections.extend(["\n\n".join(property_blocks), ""])
    sections.append("====\n")
    return "\n".join(sections)


def _render_action_operator(
    *,
    action: FsirAction,
    outcome: ActionOutcome | None,
    op_name: str,
    event_id: str,
    state_names: dict[str, str],
    predecessors: list[str],
    selected_branch: str | None,
    all_state_vars: list[str],
    action_by_id: dict[str, FsirAction],
) -> str:
    updates = outcome.updates if outcome is not None else action.updates
    guard = action.guard
    lines = [
        f"{op_name} ==",
        f"  \\* FSIR action {action.id}"
        + (f", outcome {outcome.id}" if outcome is not None else ""),
        f'  /\\ ~("{action.id}" \\in done)',
    ]
    if selected_branch is not None:
        lines.append(f'  /\\ selectedBranch = "{selected_branch}"')
    if predecessors:
        lines.append(
            "  /\\ "
            + _tla_set(sorted(predecessors))
            + " \\subseteq done"
        )
    lines.append(
        "  /\\ " + _expression(guard, state_names, action_by_id)
    )
    if outcome is not None:
        lines.append(
            "  /\\ " + _expression(outcome.guard, state_names, action_by_id)
        )
    update_by_target = {update.target_state_id: update for update in updates}
    changed: set[str] = set()
    for state_id, update in sorted(update_by_target.items()):
        tla_name = state_names[state_id]
        value = _expression(update.value, state_names, action_by_id)
        if update.op == "set":
            rhs = value
        elif update.op == "add":
            rhs = f"{tla_name} + ({value})"
        else:
            rhs = f"{tla_name} - ({value})"
        lines.append(f"  /\\ {tla_name}' = {rhs}")
        changed.add(tla_name)
    unchanged = sorted(set(all_state_vars) - changed)
    if unchanged:
        lines.append("  /\\ UNCHANGED <<" + ", ".join(unchanged) + ">>")
    lines.extend(
        [
            f'  /\\ done\' = done \\cup {{"{action.id}"}}',
            f'  /\\ lastEvent\' = "{event_id}"',
            "  /\\ UNCHANGED selectedBranch",
        ]
    )
    return "\n".join(lines)


def _render_assumptions(
    document: FsirDocument,
    action_names: dict[tuple[str, str | None], str],
    assumption_names: dict[str, str],
) -> tuple[list[str], str]:
    blocks: list[str] = []
    clause_names: list[str] = []
    action_by_id = {action.id: action for action in document.actions}
    for assumption in document.assumptions:
        prefix = "WF_vars" if assumption.kind == "weak_fairness" else "SF_vars"
        terms: list[str] = []
        for action_id in assumption.action_ids:
            action = action_by_id[action_id]
            if action.kind == "conditional_outcome":
                names = [
                    action_names[(action.id, outcome.id)]
                    for outcome in action.outcomes
                ]
                combined = "(" + " \\/ ".join(names) + ")"
                terms.append(f"{prefix}({combined})")
            else:
                terms.append(
                    f"{prefix}({action_names[(action.id, None)]})"
                )
        assumption_name = assumption_names[assumption.id]
        blocks.append(
            f"{assumption_name} == " + " /\\ ".join(terms)
        )
        clause_names.append(assumption_name)
    return blocks, "".join(f" /\\ {name}" for name in clause_names)


def _property_expression(
    prop: Property,
    state_names: dict[str, str],
    action_by_id: dict[str, FsirAction],
) -> str:
    expression = _expression(prop.formula, state_names, action_by_id)
    if prop.kind == "liveness" and prop.formula.op != "eventually":
        raise UnsupportedFsirError(
            f"liveness property {prop.id} requires eventually"
        )
    return expression


def _expression(
    expression: Expression,
    state_names: dict[str, str],
    action_by_id: dict[str, FsirAction],
) -> str:
    op = expression.op
    if op == "literal":
        return _tla_value(expression.value)
    if op == "set_literal":
        return _tla_set(expression.values)
    if op == "state_ref":
        return state_names[expression.state_id]  # type: ignore[index]
    if op == "action_parameter_ref":
        parameters = {
            item.name: item.value
            for item in action_by_id[expression.action_id].parameters  # type: ignore[index]
        }
        return _tla_value(parameters[expression.parameter_name])  # type: ignore[index]
    if op == "well_typed_state":
        return "TRUE"
    if op == "precedence":
        before, after = expression.event_ids
        return f'("{after}" \\in done => "{before}" \\in done)'
    if op == "not":
        return "~(" + _expression(expression.args[0], state_names, action_by_id) + ")"
    if op in {"and", "or"}:
        joiner = " /\\ " if op == "and" else " \\/ "
        return "(" + joiner.join(
            _expression(item, state_names, action_by_id)
            for item in expression.args
        ) + ")"
    if op in {"always", "eventually"}:
        prefix = "[]" if op == "always" else "<>"
        return prefix + "(" + _expression(
            expression.args[0], state_names, action_by_id
        ) + ")"
    operators = {
        "eq": "=",
        "neq": "#",
        "gte": ">=",
        "gt": ">",
        "lte": "<=",
        "lt": "<",
        "add": "+",
        "sub": "-",
        "in": "\\in",
    }
    if op not in operators:
        raise UnsupportedFsirError(f"unsupported expression operator {op!r}")
    left = _expression(expression.left, state_names, action_by_id)  # type: ignore[arg-type]
    right = _expression(expression.right, state_names, action_by_id)  # type: ignore[arg-type]
    return f"({left} {operators[op]} {right})"


def _render_cfg(
    document: FsirDocument,
    property_names: dict[str, str],
) -> str:
    invariants = [
        property_names[prop.id]
        for prop in document.properties
        if prop.kind in {"invariant", "action_constraint", "trace"}
        and prop.formula.op != "always"
    ]
    temporal = [
        property_names[prop.id]
        for prop in document.properties
        if prop.kind == "liveness" or prop.formula.op == "always"
    ]
    lines = ["SPECIFICATION Spec", "", "CHECK_DEADLOCK FALSE"]
    if invariants:
        lines.extend(["", "INVARIANTS", *[f"  {item}" for item in invariants]])
    if temporal:
        lines.extend(["", "PROPERTIES", *[f"  {item}" for item in temporal]])
    return "\n".join(lines) + "\n"


def _source_map(
    document: FsirDocument,
    module: str,
    state_names: dict[str, str],
    action_names: dict[tuple[str, str | None], str],
    property_names: dict[str, str],
    assumption_names: dict[str, str],
    branch_names: dict[str, str],
) -> dict[str, Any]:
    operators: dict[str, Any] = {}
    for action in document.actions:
        if action.kind == "conditional_outcome":
            for outcome in action.outcomes:
                operators[action_names[(action.id, outcome.id)]] = {
                    "fsir_action_id": action.id,
                    "fsir_outcome_id": outcome.id,
                    "source_span_ids": sorted(
                        set(action.source_span_ids + outcome.source_span_ids)
                    ),
                }
        else:
            operators[action_names[(action.id, None)]] = {
                "fsir_action_id": action.id,
                "source_span_ids": list(action.source_span_ids),
            }
    return {
        "schema_version": SOURCE_MAP_VERSION,
        "fsir_document_id": document.meta.id,
        "module_name": module,
        "states": {
            variable.id: {
                "tla_variable": state_names[variable.id],
                "observable": variable.observable,
                "source_span_ids": list(variable.source_span_ids),
            }
            for variable in document.state
        },
        "operators": operators,
        "properties": {
            property_names[prop.id]: {
                "fsir_property_id": prop.id,
                "kind": prop.kind,
                "finding_code": prop.finding_code,
                "source_span_ids": list(prop.source_span_ids),
            }
            for prop in document.properties
        },
        "assumptions": {
            assumption_names[assumption.id]: {
                "fsir_assumption_id": assumption.id,
                "kind": assumption.kind,
                "action_ids": list(assumption.action_ids),
                "source_span_ids": list(assumption.source_span_ids),
            }
            for assumption in document.assumptions
        },
        "branches": {
            branch_names[branch.id]: {
                "fsir_branch_id": branch.id,
                "action_ids": list(branch.action_ids),
            }
            for branch in document.control.branches
        },
    }


def _manifest(
    *,
    document: FsirDocument,
    module_name: str,
    input_payload: str,
    tla_text: str,
    cfg_text: str,
    source_map_text: str,
    tla_tools_jar: Path | None,
) -> dict[str, Any]:
    lowerer_source = Path(__file__).read_bytes()
    tool_hashes: dict[str, Any] = {
        "lowerer": {
            "identity": LOWERER_VERSION,
            "sha256": hashlib.sha256(lowerer_source).hexdigest(),
        },
        "fsir_contract": {
            "identity": "fsir-0.1",
            "sha256": hashlib.sha256(
                Path(fsir_contract.__file__).read_bytes()
            ).hexdigest(),
        },
        "tlc": None,
    }
    if tla_tools_jar is not None:
        resolved = tla_tools_jar.resolve()
        if not resolved.is_file():
            raise ValueError(f"TLA+ tools jar does not exist: {resolved}")
        tool_hashes["tlc"] = {
            "identity": "tla2tools.jar",
            "sha256": _sha256_file(resolved),
        }
    return {
        "schema_version": MANIFEST_VERSION,
        "fsir_document_id": document.meta.id,
        "module_name": module_name,
        "hash_algorithm": "sha256",
        "inputs": {
            "fsir_canonical_json": hashlib.sha256(
                input_payload.encode("utf-8")
            ).hexdigest(),
            "source_document": document.meta.source_document_sha256,
            "policy_snapshot": document.policy.source_sha256,
        },
        "outputs": {
            "model": hashlib.sha256(tla_text.encode("utf-8")).hexdigest(),
            "config": hashlib.sha256(cfg_text.encode("utf-8")).hexdigest(),
            "source_map": hashlib.sha256(
                source_map_text.encode("utf-8")
            ).hexdigest(),
        },
        "tools": tool_hashes,
    }


def _parse_tlc_states(output: str) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in output.splitlines():
        if re.match(r"^State \d+:", line):
            prior = current
            if current is not None:
                states.append(current)
            current = (
                dict(prior)
                if "Stuttering" in line and prior is not None
                else {}
            )
            continue
        if current is None:
            continue
        match = re.match(r"^/\\\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)$", line)
        if match:
            current[match.group(1)] = _parse_tlc_value(match.group(2).strip())
    if current is not None:
        states.append(current)
    return states


def _parse_tlc_value(value: str) -> Any:
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _module_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"Fsir_{cleaned}"
    return cleaned


def _stable_name(prefix: str, stable_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]", "_", stable_id)
    if not slug or not slug[0].isalpha():
        slug = f"Id_{slug}"
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{slug}_{digest}"


def _stable_token(prefix: str, stable_id: str) -> str:
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}.{digest}"


def _tla_set(values: Iterable[Any]) -> str:
    return "{" + ", ".join(_tla_value(item) for item in values) + "}"


def _tla_value(value: Any) -> str:
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        if any(ord(character) < 32 for character in value):
            raise UnsupportedFsirError(
                "TLA+ string literals cannot contain control characters"
            )
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise UnsupportedFsirError(f"unsupported TLA+ scalar value {value!r}")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_unique_generated_names(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise UnsupportedFsirError(
            f"stable generated {label} collision; change the conflicting FSIR IDs"
        )
