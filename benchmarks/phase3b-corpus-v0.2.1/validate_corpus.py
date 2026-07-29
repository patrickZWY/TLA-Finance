#!/usr/bin/env python3
"""Validate Phase 3B v0.2.1 structure, evidence, references, and UI controls."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

try:
    import jsonschema
except ImportError:  # The frozen Phase 3A environment intentionally lacks it.
    jsonschema = None


ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus.json"
SCHEMA = ROOT / "corpus.schema.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def canonical_hash(value: object, *, trailing_newline: bool = True) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if trailing_newline:
        payload += "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_controls(state: str) -> dict[str, bool]:
    return {
        "approve": state == "bounded_approval_required",
        "edit": state
        in {
            "clarification_required",
            "ready_for_review",
            "verification_unavailable",
            "revision_proposed",
            "reverification_required",
            "checks_passed",
            "bounded_approval_required",
        },
        "reject": state
        in {
            "ready_for_review",
            "revision_proposed",
            "reverification_required",
            "bounded_approval_required",
        },
        "stop": state != "stopped",
        "revise": state == "violation_found",
        "rerun": state == "verification_unavailable",
        "clarify": state == "clarification_required",
        "inspect_evidence": state
        in {"violation_found", "checks_passed", "bounded_approval_required"},
        "resume": state == "stopped",
        "new_goal": state == "stopped",
        "verify": state in {"ready_for_review", "reverification_required"},
    }


def validate_schema(data: object, schema: object) -> str:
    if jsonschema is None:
        return "skipped (jsonschema unavailable; semantic gates still ran)"
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        data, schema, format_checker=jsonschema.FormatChecker()
    )
    return "passed"


def validate_fixture(fixture: dict) -> None:
    fixture_id = fixture["id"]
    document = fixture["fsir_document"]
    artifact_dir = (ROOT / fixture["artifact_directory"]).resolve()
    require(
        artifact_dir.is_relative_to(ROOT) and artifact_dir.is_dir(),
        f"{fixture_id}: artifact directory",
    )
    actions = document["actions"]
    action_ids = [action["id"] for action in actions]
    bounds = document["bounds"]
    require(
        fixture["frozen_commit"]
        == "d45efd09ffe5c77b89fcad1954d7959e54b7b8f3",
        f"{fixture_id}: commit",
    )
    require(
        document["control"]["kind"] == fixture["control_kind"],
        f"{fixture_id}: control kind",
    )
    require(
        document["control"]["nodes"] == action_ids,
        f"{fixture_id}: control nodes must cover actions exactly",
    )
    require(len(action_ids) == len(set(action_ids)), f"{fixture_id}: action IDs")
    require(
        bounds["max_actions"] == len(actions)
        and bounds["max_steps"] == len(actions)
        and bounds["max_retries"] == 0
        and bounds["time_horizon"] == 0,
        f"{fixture_id}: frozen lowerer bounds",
    )
    manifest = fixture["expected_manifest"]
    raw_manifest = json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )
    raw_document = json.loads(
        (artifact_dir / "input.fsir.json").read_text(encoding="utf-8")
    )
    require(raw_document == document, f"{fixture_id}: embedded FSIR/raw input")
    require(raw_manifest == manifest, f"{fixture_id}: exact lowering manifest")
    require(
        manifest["schema_version"] == "fsir-tla-manifest-0.1",
        f"{fixture_id}: manifest version",
    )
    for digest in (
        *manifest["inputs"].values(),
        *manifest["outputs"].values(),
        manifest["tools"]["lowerer"]["sha256"],
        manifest["tools"]["fsir_contract"]["sha256"],
        manifest["tools"]["tlc"]["sha256"],
    ):
        require(bool(SHA256.fullmatch(digest)), f"{fixture_id}: invalid SHA-256")
    require(
        manifest["tools"]["tlc"]["sha256"]
        == "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88",
        f"{fixture_id}: pinned TLC toolchain",
    )
    execution_manifest = fixture["execution_evidence_manifest"]
    raw_execution_manifest = json.loads(
        (artifact_dir / "execution-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    require(
        raw_execution_manifest == execution_manifest,
        f"{fixture_id}: exact execution-evidence manifest",
    )
    require(
        execution_manifest["schema_version"]
        == "fsir-tla-execution-evidence-0.1",
        f"{fixture_id}: execution-evidence version",
    )
    require(
        all(
            SHA256.fullmatch(digest)
            for digest in execution_manifest["artifacts"].values()
        ),
        f"{fixture_id}: execution-evidence SHA-256",
    )
    require(
        manifest["inputs"]["fsir_canonical_json"]
        == canonical_hash(document, trailing_newline=False),
        f"{fixture_id}: canonical FSIR digest",
    )
    require(
        manifest["inputs"]["source_document"]
        == document["meta"]["source_document_sha256"],
        f"{fixture_id}: source-document digest binding",
    )
    require(
        manifest["inputs"]["policy_snapshot"]
        == document["policy"]["source_sha256"],
        f"{fixture_id}: policy-snapshot digest binding",
    )
    require(
        manifest["outputs"]["model"]
        == file_hash(artifact_dir / f"{fixture['module_name']}.tla")
        and manifest["outputs"]["config"]
        == file_hash(artifact_dir / f"{fixture['module_name']}.cfg")
        and manifest["outputs"]["source_map"]
        == file_hash(artifact_dir / "source-map.json"),
        f"{fixture_id}: lowering output digest binding",
    )
    execution_files = {
        "classification": "classification.json",
        "execution_report": "execution-report.json",
        "lowering_manifest": "manifest.json",
        "normalized_trace": "normalized-trace.json",
        "tlc_output": "tlc-output.txt",
    }
    require(
        all(
            execution_manifest["artifacts"][name]
            == file_hash(artifact_dir / filename)
            for name, filename in execution_files.items()
        ),
        f"{fixture_id}: raw execution artifact digest binding",
    )
    possible_events = set(action_ids)
    for action in actions:
        possible_events.update(outcome["id"] for outcome in action["outcomes"])
    require(
        set(fixture["expected_normalized_event_ids"]) <= possible_events,
        f"{fixture_id}: normalized trace references unknown action/outcome",
    )
    property_ids = {prop["id"] for prop in document["properties"]}
    require(
        set(fixture["expected_property_ids"]) <= property_ids,
        f"{fixture_id}: classified property reference",
    )
    if fixture["expected_tlc_verdict"] == "property_violation":
        require(
            fixture["expected_property_ids"]
            and fixture["expected_normalized_event_ids"],
            f"{fixture_id}: property-violation evidence",
        )
    classification = json.loads(
        (artifact_dir / "classification.json").read_text(encoding="utf-8")
    )
    execution_report = json.loads(
        (artifact_dir / "execution-report.json").read_text(encoding="utf-8")
    )
    normalized_trace = json.loads(
        (artifact_dir / "normalized-trace.json").read_text(encoding="utf-8")
    )
    require(
        classification["kind"] == fixture["expected_tlc_verdict"]
        and classification["violated_property_ids"]
        == fixture["expected_property_ids"],
        f"{fixture_id}: exact TLC classification",
    )
    require(execution_report["satisfied"], f"{fixture_id}: execution report")
    require(
        [step["event_id"] for step in normalized_trace]
        == fixture["expected_normalized_event_ids"],
        f"{fixture_id}: raw normalized trace",
    )
    direction = fixture["source_map_direction"]
    require(
        direction
        == {
            "states": "fsir_state_id_to_generated_entry",
            "operators": "generated_operator_to_fsir_action_and_optional_outcome",
            "properties": "generated_property_to_fsir_property",
            "branches": "generated_branch_to_fsir_branch",
        },
        f"{fixture_id}: source-map direction",
    )


def validate_case(
    case: dict, policy_ids: set[str], fixtures_by_id: dict[str, dict]
) -> None:
    case_id = case["id"]
    semantics = case["expected_semantics"]
    span_ids = {span["id"] for span in case["source_spans"]}
    action_ids = {action["id"] for action in semantics["actions"]}
    property_ids = {prop["id"] for prop in semantics["properties"]}
    state_ids = set(semantics["state_ids"])

    require(case["policy_profile_id"] in policy_ids, f"{case_id}: policy")
    require(property_ids, f"{case_id}: no expected property")
    for action in semantics["actions"]:
        require(
            set(action["source_span_ids"]) <= span_ids,
            f"{case_id}: unresolved semantic action span",
        )
    for prop in semantics["properties"]:
        require(
            set(prop.get("source_span_ids", [])) <= span_ids,
            f"{case_id}: unresolved semantic property span",
        )
    require(
        set(case["evidence"]["property_ids"]) <= property_ids,
        f"{case_id}: evidence property reference",
    )
    require(
        case["positive_traces"]
        and case["negative_traces"]
        and case["mutants"],
        f"{case_id}: missing witness or mutant",
    )
    for trace in case["positive_traces"] + case["negative_traces"]:
        require(
            set(trace["semantic_event_ids"]) <= action_ids,
            f"{case_id}: semantic trace action reference",
        )

    lowering = case["lowering_oracle"]
    expectation = lowering["expectation"]
    require(
        lowering["frozen_commit"]
        == "d45efd09ffe5c77b89fcad1954d7959e54b7b8f3",
        f"{case_id}: lowerer commit",
    )
    if expectation == "lower":
        require(lowering["emits_artifacts"], f"{case_id}: lower artifacts")
        require(
            lowering["fixture_id"] in fixtures_by_id, f"{case_id}: fixture"
        )
        require(lowering["expected_rejection"] is None, f"{case_id}: rejection")
        fixture_document = fixtures_by_id[lowering["fixture_id"]]["fsir_document"]
        fixture_action_ids = {action["id"] for action in fixture_document["actions"]}
        fixture_event_ids = set(fixture_action_ids)
        for action in fixture_document["actions"]:
            fixture_event_ids.update(
                outcome["id"] for outcome in action["outcomes"]
            )
        fixture_property_ids = {
            prop["id"] for prop in fixture_document["properties"]
        }
        require(
            set(lowering["semantic_action_map"]) == action_ids,
            f"{case_id}: complete semantic action-map keys",
        )
        require(
            {
                event
                for events in lowering["semantic_action_map"].values()
                for event in events
            }
            <= fixture_event_ids,
            f"{case_id}: backend action/outcome map values",
        )
        require(
            set(lowering["semantic_property_map"]) == property_ids,
            f"{case_id}: complete semantic property-map keys",
        )
        require(
            set(lowering["semantic_property_map"].values())
            <= fixture_property_ids,
            f"{case_id}: backend property-map values",
        )
    else:
        require(not lowering["emits_artifacts"], f"{case_id}: no artifacts")
        require(lowering["fixture_id"] is None, f"{case_id}: no fixture")
        require(lowering["expected_rejection"], f"{case_id}: rejection oracle")

    product = case["product_projection"]
    node_ids = {node["id"] for node in product["nodes"]}
    projected_property_ids = {prop["id"] for prop in product["properties"]}
    require(
        product["case_id"] == case_id
        and product["source_text"] == case["prose"],
        f"{case_id}: product identity/source",
    )
    require(node_ids == action_ids, f"{case_id}: product nodes")
    require(
        projected_property_ids == property_ids,
        f"{case_id}: product properties",
    )
    for question in product["questions"]:
        require(
            question["source_span"] in span_ids,
            f"{case_id}: question source span",
        )
    for node in product["nodes"]:
        require(
            set(node["source_spans"]) <= span_ids,
            f"{case_id}: node source span",
        )
    for finding in product["findings"]:
        require(
            finding["property_id"] in projected_property_ids,
            f"{case_id}: finding property",
        )
        require(
            finding["node_id"] is None or finding["node_id"] in node_ids,
            f"{case_id}: finding node",
        )
        require(
            finding["state_id"] is None or finding["state_id"] in state_ids,
            f"{case_id}: finding state",
        )

    state = product["agent_phase"]
    require(
        product["controls"] == expected_controls(state),
        f"{case_id}: state/control permissions",
    )
    approval_actions = set(product["approval_scope"]["actions"])
    require(approval_actions <= node_ids, f"{case_id}: approval action reference")
    if state == "bounded_approval_required":
        require(
            product["controls"]["approve"] and approval_actions == node_ids,
            f"{case_id}: bounded approval scope",
        )
    else:
        require(
            not product["controls"]["approve"] and not approval_actions,
            f"{case_id}: approval must be disabled",
        )

    verification = product["verification"]
    if state == "verification_unavailable" or verification["status"] == "inconclusive":
        require(
            verification["reason_code"] is not None and verification["message"],
            f"{case_id}: structured unavailable reason",
        )
    else:
        require(
            verification["reason_code"] is None
            and verification["message"] is None,
            f"{case_id}: unexpected unavailable reason",
        )

    counterexample = product["counterexample"]
    if case["evidence"]["verdict"] == "fail":
        events = case["negative_traces"][0]["semantic_event_ids"]
        path = counterexample["path"]
        require(len(path) == len(events) + 1, f"{case_id}: path length")
        require(
            path[0]["action_node_id"] is None and not path[0]["violations"],
            f"{case_id}: initial state linkage",
        )
        require(
            [step["action_node_id"] for step in path[1:]] == events,
            f"{case_id}: normalized action order",
        )
        for step in path:
            require(step["balances"], f"{case_id}: empty balance snapshot")
            require(
                set(step["violations"]) <= projected_property_ids,
                f"{case_id}: counterexample property reference",
            )
        violating = [step for step in path if step["violations"]]
        require(violating, f"{case_id}: no violating state")
        require(
            counterexample["first_violating_state"]
            == violating[0]["state_id"],
            f"{case_id}: earliest violating state",
        )
        require(
            not any(step["violations"] for step in path[: path.index(violating[0])]),
            f"{case_id}: early violation marker",
        )
        require(
            all(finding["node_id"] == events[-1] for finding in product["findings"]),
            f"{case_id}: finding must identify failing transition",
        )
    else:
        require(
            counterexample["first_violating_state"] is None
            and not counterexample["path"],
            f"{case_id}: unexpected counterexample",
        )


def validate_hero(hero: dict) -> None:
    stages = hero["hero_stages"]
    states = [stage["state"] for stage in stages]
    require(
        states
        == [
            "clarification_required",
            "ready_for_review",
            "verification_running",
            "violation_found",
            "revision_proposed",
            "reverification_required",
            "checks_passed",
            "bounded_approval_required",
        ],
        "hero state sequence",
    )
    contract = {
        "properties": hero["expected_semantics"]["properties"],
        "assumptions": hero["expected_semantics"]["assumption_ids"],
        "bounds": hero["bounds"],
    }
    contract_hash = canonical_hash(contract)
    snapshots = [stage["projection_snapshot"] for stage in stages]
    require(
        all(snapshot["contract_hash"] == contract_hash for snapshot in snapshots),
        "hero property/assumption/bound preservation hash",
    )
    for state, snapshot in zip(states, snapshots, strict=True):
        require(
            snapshot["controls"] == expected_controls(state),
            f"hero {state}: controls",
        )
    require(
        snapshots[3]["counterexample"]["fixture_id"]
        == "fixture.phase3a.lifecycle.concurrent",
        "hero violation fixture",
    )
    require(
        snapshots[5]["evidence_status"] == "stale"
        and snapshots[5]["stale_evidence"]["version"] == "fsir.core.30.v0"
        and snapshots[5]["fsir_version"] == "fsir.core.30.v1",
        "hero v0 evidence invalidation",
    )
    require(
        snapshots[6]["evidence_status"] == "fresh"
        and snapshots[6]["model_hash"] != snapshots[3]["model_hash"],
        "hero fresh re-verification hash",
    )
    require(
        snapshots[7]["approval_scope"]
        and snapshots[7]["controls"]["approve"],
        "hero bounded approval",
    )


def main() -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema_result = validate_schema(data, schema)

    cases = data["cases"]
    require(
        [case["id"] for case in cases]
        == [f"core.{number:02d}" for number in range(1, 31)],
        "cases must be core.01 through core.30",
    )
    fixtures = data["backend_fixtures"]
    for fixture in fixtures:
        validate_fixture(fixture)
    fixtures_by_id = {fixture["id"]: fixture for fixture in fixtures}
    require(len(fixtures_by_id) == len(fixtures), "duplicate backend fixture ID")
    policy_ids = {profile["id"] for profile in data["policy_profiles"]}
    for case in cases:
        validate_case(case, policy_ids, fixtures_by_id)
    validate_hero(cases[-1])

    levels = Counter(case["level"] for case in cases)
    verdicts = Counter(case["evidence"]["verdict"] for case in cases)
    lowering = Counter(case["lowering_oracle"]["expectation"] for case in cases)
    print(
        f"valid: {len(cases)} cases; schema={schema_result}; "
        f"levels={dict(levels)}; verdicts={dict(verdicts)}; "
        f"lowering={dict(lowering)}; "
        f"mutants={sum(len(case['mutants']) for case in cases)}"
    )


if __name__ == "__main__":
    main()
