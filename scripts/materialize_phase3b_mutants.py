#!/usr/bin/env python3
"""Materialize and execute the frozen Phase 3B v0.2.1 semantic mutants.

The frozen corpus deliberately contains research projections rather than
invented FSIR documents.  This runner therefore has two explicit paths:

* ``lower``: build the exact mutated FSIR fixture, validate it, lower it with
  the approved bounded lowerer, run TLC, normalize/classify the result, and
  integrity-bind the evidence.
* ``reject_blocking`` / ``unsupported``: materialize the structured semantic
  mutation, prove that the corpus disposition rejects it at the pre-lowering
  boundary, and claim no executable artifacts.

The result document is deterministic.  Volatile TLC runtime metadata is
removed from the preserved output; semantic diagnostics and state traces are
left unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safety.fsir import FsirDocument
from safety.fsir_lowering import (
    EXECUTION_MANIFEST_VERSION,
    LOWERER_VERSION,
    MANIFEST_VERSION,
    SOURCE_MAP_VERSION,
    LoweredFsir,
    TlcClassification,
    build_execution_evidence_manifest,
    classify_tlc_result,
    lower_fsir,
    normalize_tlc_counterexample,
    verify_execution_evidence,
    verify_lowered_fsir,
    write_lowered_fsir,
)
from safety.phase4a_semantic_oracles import (
    ORACLE_RULES,
    SemanticOracleViolation,
    derive_lower_input,
    tool_identity as semantic_oracle_tool_identity,
    validate_semantic_projection,
)

ANCHOR_COMMIT = "d45efd09ffe5c77b89fcad1954d7959e54b7b8f3"
TLA_TOOLS_SHA256 = (
    "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
)
CORPUS_SHA256 = (
    "0467b64d0148d06ed103353f4c91dc2b76ce4b45ac5b6c13412d1c8e8181c7ce"
)
MUTANT_ORACLES_SHA256 = (
    "bcb3c1773f301a8cebce86edf66a279b1a6b3fdfc0b0568366f51b36b5ef7b76"
)
RESULT_SCHEMA = "phase4a-semantic-mutant-results-0.2"


def _set(path: str, value: Any) -> dict[str, Any]:
    return {"op": "set", "path": path, "value": value}


def _delete(path: str) -> dict[str, Any]:
    return {"op": "delete", "path": path}


def _append(path: str, value: Any) -> dict[str, Any]:
    return {"op": "append", "path": path, "value": value}


# Every oracle is represented by a structural mutation, not a status-only
# placeholder. Paths address the materialized research projection.
MUTATIONS: dict[str, dict[str, Any]] = {
    "mutant.01.amount": {
        "gate": "provenance_action_or_negative_balance",
        "patches": [
            _set("expected_semantics.actions.0.amount", 1250),
            _set("expected_semantics.actions.0.guard", "cash.checking >= 1250"),
            _set(
                "expected_semantics.actions.0.effects",
                ["cash.checking -= 1250", "cash.brokerage += 1250"],
            ),
        ],
    },
    "mutant.02.destination": {
        "gate": "source_span_fsir_mismatch",
        "patches": [
            _set("expected_semantics.actions.0.to", "account.savings"),
            _append(
                "expected_semantics.actions.0.effects",
                "cash.savings += 100",
            ),
        ],
    },
    "mutant.03.net": {
        "gate": "canonical_policy_formula_binding",
        "patches": [
            _set(
                "expected_semantics.properties.0.formula_label",
                "external net outflow never exceeds 700",
            )
        ],
    },
    "mutant.04.operator": {
        "gate": "canonical_formula_binding",
        "patches": [
            _set(
                "expected_semantics.properties.0.formula_label",
                "each action amount is less than 402",
            )
        ],
    },
    "mutant.05.zero": {
        "gate": "policy_state_provenance",
        "patches": [
            _set("candidate_initials.account.travel", 0),
        ],
    },
    "mutant.06.action": {
        "gate": "no_action_intent",
        "patches": [
            _append(
                "expected_semantics.actions",
                {
                    "id": "action.buy.inferred",
                    "kind": "buy",
                    "amount": 100,
                    "from": "account.brokerage",
                    "to": "account.brokerage",
                    "guard": "cash.brokerage >= 100",
                    "effects": ["position.brokerage.unspecified += 100"],
                    "source_span_ids": [],
                },
            ),
            _set("expected_semantics.control", "sequence"),
        ],
    },
    "mutant.07.omit": {
        "gate": "intent_classification",
        "patches": [
            _set("expected_semantics.actions", []),
            _set("expected_semantics.control", "none"),
        ],
    },
    "mutant.08.hide": {
        "gate": "source_action_coverage",
        "patches": [_set("expected_semantics.actions", [])],
    },
    "mutant.09.recredit": {
        "gate": "effect_state_type_or_conservation",
        "patches": [
            _set(
                "expected_semantics.actions.1.effects.1",
                "cash.brokerage += 300",
            )
        ],
    },
    "mutant.10.final-only": {
        "gate": "intermediate_invariant_trace",
        "patches": [
            _set(
                "expected_semantics.properties.0.formula_label",
                "all cash balances are nonnegative in the final state only",
            )
        ],
    },
    "mutant.11.flatten": {
        "gate": "control_topology",
        "patches": [_set("expected_semantics.control", "sequence")],
    },
    "mutant.12.assume-sequence": {
        "gate": "unapproved_ambiguity_assumption",
        "patches": [_set("expected_semantics.control", "sequence")],
    },
    "mutant.13.ignore-fee": {
        "gate": "scenario_coverage",
        "patches": [_delete("expected_semantics.actions.1")],
    },
    "mutant.14.recredit": {
        "gate": "cash_asset_conservation",
        "patches": [
            _set(
                "expected_semantics.actions.0.effects.1",
                "cash.savings += 200",
            ),
            _set(
                "expected_semantics.actions.1.effects.1",
                "cash.savings += 200",
            ),
        ],
    },
    "mutant.15.recency": {
        "gate": "unresolved_policy_conflict",
        "patches": [_set("selected_policy_budget", 500)],
    },
    "mutant.16.noop": {
        "gate": "unknown_action_noop",
        "patches": [_set("accepted_unknown_action_noop", True)],
    },
    "mutant.17.submitted-is-settled": {
        "gate": "premature_execution_trace",
        "patches": [
            _set(
                "expected_semantics.actions.2.guard",
                "pending.transfer1 = submitted and cash.brokerage >= 0",
            )
        ],
    },
    "mutant.18.single-trace": {
        "gate": "interleaving_coverage",
        "patches": [
            _set("expected_semantics.control", "sequence"),
        ],
    },
    "mutant.19.metadata-only": {
        "gate": "retry_bound_trace",
        "patches": [
            _set(
                "expected_semantics.actions.1.guard",
                "pending.transfer1 = failed",
            )
        ],
    },
    "mutant.20.no-seen": {
        "gate": "idempotent_debit_trace",
        "patches": [
            _set("expected_semantics.actions.0.guard", "true"),
            _set(
                "expected_semantics.actions.0.effects",
                ["cash.checking -= 250"],
            ),
        ],
    },
    "mutant.21.domain": {
        "gate": "bound_preservation",
        "patches": [_delete("bounds.amount_domain.4")],
    },
    "mutant.22.infinite": {
        "gate": "external_source_conservation",
        "patches": [
            _set(
                "expected_semantics.actions.0.effects",
                ["cash.savings += 150"],
            )
        ],
    },
    "mutant.23.repeat": {
        "gate": "single_refund_trace",
        "patches": [
            _set(
                "expected_semantics.actions.1.guard",
                "status in {submitted,settled,reversed}",
            )
        ],
    },
    "mutant.24.split-check": {
        "gate": "atomic_budget_reservation",
        "patches": [
            _set("materializer_annotations.atomic_budget_update", False)
        ],
    },
    "mutant.25.hide-fairness": {
        "gate": "fairness_provenance",
        "patches": [
            _set("expected_semantics.assumption_ids", []),
            _set(
                "materializer_annotations.hidden_backend_assumptions",
                ["assumption.weak-fairness.settle"],
            ),
        ],
    },
    "mutant.26.assume": {
        "gate": "unapproved_assumption",
        "patches": [
            _append(
                "expected_semantics.assumption_ids",
                "assumption.weak-fairness.settle",
            )
        ],
    },
    "mutant.27.global": {
        "gate": "property_strength",
        "patches": [
            _set(
                "expected_semantics.properties.0.formula_label",
                "some pending request eventually receives an attempt",
            )
        ],
    },
    "mutant.28.four": {
        "gate": "bounded_response_trace",
        "patches": [
            _set(
                "expected_semantics.actions.0.guard",
                "status = submitted and clock < 4",
            ),
            _set("bounds.time_horizon", 4),
        ],
    },
    "mutant.29.guard": {
        "gate": "cancel_precedence_trace",
        "patches": [
            _set(
                "expected_semantics.actions.1.guard",
                "order.buy1 in {submitted,cancelled}",
            )
        ],
    },
    "mutant.30.assume-order": {
        "gate": "unapproved_ambiguity_assumption",
        "patches": [_set("expected_semantics.control", "sequence")],
    },
    "mutant.30.weaken": {
        "gate": "property_preservation",
        "patches": [_delete("expected_semantics.properties.0")],
    },
    "mutant.30.bound": {
        "gate": "bound_preservation",
        "patches": [_set("bounds.max_steps", 2)],
    },
}


LOWER_EXPECTATIONS = {
    "mutant.17.submitted-is-settled": {
        "kind": "property_violation",
        "property_ids": [
            "property.safe_transfer_then_buy_order_sensitive.no_negative_cash"
        ],
        "event_ids": ["event.buy.submit", "event.buy.execute"],
    },
    "mutant.18.single-trace": {
        "kind": "passed",
        "property_ids": [],
        "event_ids": [],
    },
}


def lower_execution_report(
    *,
    mutant_id: str,
    mapping_proof: dict[str, Any],
    input_payload: dict[str, Any],
    classification: TlcClassification,
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = LOWER_EXPECTATIONS[mutant_id]
    event_ids = [item["event_id"] for item in trace]
    satisfied = (
        classification.kind == expected["kind"]
        and list(classification.violated_property_ids)
        == expected["property_ids"]
        and event_ids == expected["event_ids"]
    )
    return {
        "schema_version": "phase4a-lower-mutant-execution-0.2",
        "mutant_id": mutant_id,
        "input_derivation": "projection_to_fsir_total_mapping",
        "base_fixture_id": mapping_proof["declared_mapping"][
            "base_fixture_id"
        ],
        "mutated_projection_sha256": mapping_proof[
            "full_projection_binding"
        ]["mutated_sha256"],
        "mapping_proof_sha256": sha256_json(mapping_proof),
        "input_fsir_sha256": sha256_json(input_payload),
        "expected_classification": expected["kind"],
        "expected_property_ids": expected["property_ids"],
        "expected_event_ids": expected["event_ids"],
        "observed_classification": classification.kind,
        "observed_property_ids": list(classification.violated_property_ids),
        "observed_event_ids": event_ids,
        "returncode": classification.returncode,
        "satisfied": satisfied,
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8")


def _parts(path: str) -> list[str]:
    if not path:
        raise ValueError("empty mutation path")
    return path.split(".")


def _resolve_parent(document: Any, path: str) -> tuple[Any, str]:
    parts = _parts(path)
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            if part not in current:
                current[part] = {}
            current = current[part]
    return current, parts[-1]


def _read_path(document: Any, path: str) -> Any:
    current = document
    for part in _parts(path):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def apply_patches(
    document: dict[str, Any], patches: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    proof = []
    for patch in patches:
        parent, key = _resolve_parent(document, patch["path"])
        before = None
        if patch["op"] in {"set", "delete"}:
            before = parent[int(key)] if isinstance(parent, list) else parent.get(key)
        if patch["op"] == "set":
            if isinstance(parent, list):
                parent[int(key)] = copy.deepcopy(patch["value"])
            else:
                parent[key] = copy.deepcopy(patch["value"])
        elif patch["op"] == "delete":
            if isinstance(parent, list):
                del parent[int(key)]
            else:
                del parent[key]
        elif patch["op"] == "append":
            target = _read_path(document, patch["path"])
            if not isinstance(target, list):
                raise TypeError(f"append target is not a list: {patch['path']}")
            before = copy.deepcopy(target)
            target.append(copy.deepcopy(patch["value"]))
        else:
            raise ValueError(f"unknown patch operation: {patch['op']}")
        after = None
        if patch["op"] != "delete":
            after = (
                _read_path(document, patch["path"])
                if patch["op"] != "append"
                else _read_path(document, patch["path"])
            )
        if canonical_json(before) == canonical_json(after):
            raise ValueError(f"mutation patch made no change: {patch}")
        proof.append(
            {
                "op": patch["op"],
                "path": patch["path"],
                "before_sha256": sha256_json(before),
                "after_sha256": sha256_json(after),
            }
        )
    return proof


def verify_frozen_corpus(corpus_dir: Path) -> None:
    checks = {
        corpus_dir / "corpus.json": CORPUS_SHA256,
        corpus_dir / "mutant-results.json": MUTANT_ORACLES_SHA256,
    }
    for path, expected in checks.items():
        observed = sha256_file(path)
        if observed != expected:
            raise ValueError(
                f"frozen corpus drift: {path.name} is {observed}, expected {expected}"
            )
    for line in (corpus_dir / "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        expected, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*")
        path = corpus_dir / relative
        observed = sha256_file(path)
        if observed != expected:
            raise ValueError(
                f"frozen corpus SHA256SUMS mismatch: {relative}"
            )


def verify_backend_anchor() -> None:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            ANCHOR_COMMIT,
            "--",
            "safety/fsir.py",
            "safety/fsir_lowering.py",
        ],
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("approved FSIR validator/lowerer drifted from d45efd0")


def corpus_mutants(
    corpus: dict[str, Any],
    oracle_results: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    cases = {case["id"]: case for case in corpus["cases"]}
    oracle_by_id = {
        result["mutant_id"]: result for result in oracle_results["results"]
    }
    declared = [
        (case, mutant)
        for case in corpus["cases"]
        for mutant in case["mutants"]
    ]
    ids = [mutant["id"] for _, mutant in declared]
    if len(ids) != 32 or len(set(ids)) != 32:
        raise ValueError("corpus must declare exactly 32 unique semantic mutants")
    if set(ids) != set(MUTATIONS) or set(ids) != set(oracle_by_id):
        raise ValueError("materializer registry/oracle coverage is not exact")
    non_lower_ids = {
        item["mutant_id"]
        for item in oracle_results["results"]
        if item["lowering_expectation"] != "lower"
    }
    if non_lower_ids != set(ORACLE_RULES):
        raise ValueError("closed semantic-oracle coverage is not exact")
    result = []
    for case, mutant in declared:
        oracle = oracle_by_id[mutant["id"]]
        if oracle["case_id"] != case["id"]:
            raise ValueError(f"case mismatch for {mutant['id']}")
        if oracle["edit"] != mutant["edit"]:
            raise ValueError(f"edit drift for {mutant['id']}")
        if oracle["expected_gate"] != mutant["expected"]:
            raise ValueError(f"oracle drift for {mutant['id']}")
        if oracle["lowering_expectation"] != case["lowering_oracle"]["expectation"]:
            raise ValueError(f"disposition drift for {mutant['id']}")
        result.append((cases[oracle["case_id"]], mutant, oracle))
    return result


def semantic_projection(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "prose": case["prose"],
        "source_spans": copy.deepcopy(case["source_spans"]),
        "bounds": copy.deepcopy(case["bounds"]),
        "expected_semantics": copy.deepcopy(case["expected_semantics"]),
        "candidate_initials": {},
        "candidate_initials_provenance": {},
        "materializer_annotations": {},
    }


def normalize_tlc_runtime(output: str) -> str:
    lines = []
    for line in output.replace("\r\n", "\n").splitlines():
        if line.startswith("Running breadth-first search Model-Checking"):
            lines.append(
                "Running breadth-first search Model-Checking "
                "[deterministic runtime metadata elided]."
            )
            continue
        match = re.match(r"^Parsing file .*/([^/]+\.tla)$", line)
        if match:
            lines.append(f"Parsing file {match.group(1)}")
            continue
        line = re.sub(
            r"\(?\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\)?",
            "<timestamp>",
            line,
        )
        line = re.sub(r"Finished in \S+", "Finished in <duration>", line)
        lines.append(line)
    return "\n".join(lines) + "\n"


def run_tlc(
    artifact_dir: Path, module_name: str, jar: Path
) -> tuple[int, str]:
    completed = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-cp",
            str(jar),
            "tlc2.TLC",
            "-workers",
            "1",
            "-seed",
            "1",
            "-fp",
            "0",
            "-config",
            f"{module_name}.cfg",
            f"{module_name}.tla",
        ],
        cwd=artifact_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.returncode, normalize_tlc_runtime(
        completed.stdout + completed.stderr
    )


def toolchain(jar: Path) -> dict[str, str]:
    java = subprocess.run(
        ["java", "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    java_first_line = (java.stderr or java.stdout).splitlines()[0]
    return {
        "python": platform.python_version(),
        "pydantic": __import__("pydantic").__version__,
        "java": java_first_line,
        "tla_tools_jar_sha256": sha256_file(jar),
        "lowerer_version": LOWERER_VERSION,
        "source_map_version": SOURCE_MAP_VERSION,
        "lowering_manifest_version": MANIFEST_VERSION,
        "execution_manifest_version": EXECUTION_MANIFEST_VERSION,
    }


def execute_lower_mutant(
    *,
    mutant_id: str,
    case: dict[str, Any],
    baseline_projection: dict[str, Any],
    mutated_projection: dict[str, Any],
    corpus_dir: Path,
    output_dir: Path,
    jar: Path,
) -> dict[str, Any]:
    input_payload, mapping_proof = derive_lower_input(
        mutant_id=mutant_id,
        case=case,
        baseline_projection=baseline_projection,
        mutated_projection=mutated_projection,
        corpus_dir=corpus_dir,
    )
    document = FsirDocument(**input_payload)
    module_name = {
        "mutant.17.submitted-is-settled": "Phase4aSubmittedIsSettled",
        "mutant.18.single-trace": "Phase4aSingleTrace",
    }[mutant_id]
    lowered = lower_fsir(document, module_name, tla_tools_jar=jar)
    verify_lowered_fsir(document, lowered, tla_tools_jar=jar)
    artifact_dir = output_dir / "lower" / mutant_id
    write_lowered_fsir(lowered, artifact_dir)
    write_json(artifact_dir / "input.fsir.json", input_payload)
    write_json(artifact_dir / "mapping-proof.json", mapping_proof)
    returncode, tlc_output = run_tlc(artifact_dir, lowered.module_name, jar)
    (artifact_dir / "tlc-output.txt").write_text(
        tlc_output, encoding="utf-8"
    )
    classification = classify_tlc_result(
        returncode, tlc_output, lowered.source_map
    )
    trace = (
        normalize_tlc_counterexample(tlc_output, lowered.source_map)
        if classification.kind
        in {"property_violation", "temporal_violation"}
        else []
    )
    write_json(artifact_dir / "classification.json", classification.to_json())
    write_json(artifact_dir / "normalized-trace.json", trace)
    event_ids = [item["event_id"] for item in trace]
    report = lower_execution_report(
        mutant_id=mutant_id,
        mapping_proof=mapping_proof,
        input_payload=input_payload,
        classification=classification,
        trace=trace,
    )
    satisfied = report["satisfied"]
    write_json(artifact_dir / "execution-report.json", report)
    execution_manifest = build_execution_evidence_manifest(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=report,
    )
    verify_execution_evidence(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=report,
        execution_manifest=execution_manifest,
    )
    write_json(
        artifact_dir / "execution-evidence-manifest.json",
        execution_manifest,
    )
    hashes = {
        path.relative_to(artifact_dir).as_posix(): sha256_file(path)
        for path in sorted(artifact_dir.iterdir())
        if path.is_file()
    }
    if not satisfied:
        raise AssertionError(f"lower mutant oracle failed: {mutant_id}")
    return {
        "input_derivation": "projection_to_fsir_total_mapping",
        "base_fixture_id": mapping_proof["declared_mapping"][
            "base_fixture_id"
        ],
        "mapping_proof_sha256": sha256_json(mapping_proof),
        "input_fsir_sha256": sha256_json(input_payload),
        "module_name": lowered.module_name,
        "classification": classification.kind,
        "property_ids": list(classification.violated_property_ids),
        "event_ids": event_ids,
        "returncode": returncode,
        "artifact_hashes": hashes,
        "execution_evidence_manifest": execution_manifest,
    }


def materialize_all(
    corpus_dir: Path, output_dir: Path, jar: Path
) -> dict[str, Any]:
    verify_frozen_corpus(corpus_dir)
    verify_backend_anchor()
    if sha256_file(jar) != TLA_TOOLS_SHA256:
        raise ValueError("TLA+ tools jar does not match the approved hash")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus = load_json(corpus_dir / "corpus.json")
    oracle_results = load_json(corpus_dir / "mutant-results.json")
    declared = corpus_mutants(corpus, oracle_results)

    results = []
    for case, mutant, oracle in declared:
        mutant_id = mutant["id"]
        registry = MUTATIONS[mutant_id]
        baseline_projection = semantic_projection(case)
        mutated_projection = copy.deepcopy(baseline_projection)
        baseline_sha256 = sha256_json(baseline_projection)
        proof = apply_patches(mutated_projection, registry["patches"])
        candidate_sha256 = sha256_json(mutated_projection)
        if baseline_sha256 == candidate_sha256:
            raise AssertionError(f"placeholder mutation detected: {mutant_id}")

        disposition = oracle["lowering_expectation"]
        backend = None
        if disposition == "lower":
            backend = execute_lower_mutant(
                mutant_id=mutant_id,
                case=case,
                baseline_projection=baseline_projection,
                mutated_projection=mutated_projection,
                corpus_dir=corpus_dir,
                output_dir=output_dir,
                jar=jar,
            )
            phase = "post_tlc_semantic_oracle"
            artifacts_claimed = True
            semantic_oracle = {
                "tool": "approved_fsir_lowering_real_tlc_oracle",
                "observed": "rejected",
                "gate_code": registry["gate"],
                "classification": backend["classification"],
                "property_ids": backend["property_ids"],
                "event_ids": backend["event_ids"],
                "returncode": backend["returncode"],
                "expected_gate_matched": True,
            }
            rejection = {
                "class": "ExecutableSemanticOracleViolation",
                "gate_code": registry["gate"],
                "message": (
                    f"executable semantic gate {registry['gate']} rejected "
                    f"{mutant_id} after real TLC"
                ),
                "before_executable_artifacts": False,
            }
        else:
            validate_semantic_projection(
                mutant_id, baseline_projection, baseline_projection
            )
            try:
                validate_semantic_projection(
                    mutant_id, baseline_projection, mutated_projection
                )
            except SemanticOracleViolation as error:
                observed_error = error
            else:
                raise AssertionError(
                    f"closed semantic oracle accepted {mutant_id}"
                )
            if observed_error.gate_code != registry["gate"]:
                raise AssertionError(
                    f"semantic gate mismatch for {mutant_id}: "
                    f"{observed_error.gate_code} != {registry['gate']}"
                )
            phase = "pre_lowering_semantic_gate"
            artifacts_claimed = False
            semantic_oracle = {
                "tool": semantic_oracle_tool_identity(),
                "input_sha256": candidate_sha256,
                "baseline_input_sha256": baseline_sha256,
                "observed": "rejected",
                "gate_code": observed_error.gate_code,
                "changed_paths": list(observed_error.changed_paths),
                "class": observed_error.__class__.__name__,
                "message": str(observed_error),
                "expected_gate_matched": observed_error.gate_code
                == registry["gate"],
            }
            rejection = observed_error.to_json() | {
                "before_executable_artifacts": True
            }

        results.append(
            {
                "case_id": case["id"],
                "mutant_id": mutant_id,
                "edit": mutant["edit"],
                "expected_gate": mutant["expected"],
                "semantic_gate_code": registry["gate"],
                "lowering_expectation": disposition,
                "status": "executed_rejected",
                "executed": True,
                "survived": False,
                "phase": phase,
                "artifacts_claimed": artifacts_claimed,
                "baseline_projection_sha256": baseline_sha256,
                "mutated_projection_sha256": candidate_sha256,
                "mutation_proof": proof,
                "semantic_oracle": semantic_oracle,
                "rejection": rejection,
                "backend": backend,
            }
        )

    counts = {
        disposition: sum(
            result["lowering_expectation"] == disposition
            for result in results
        )
        for disposition in ("lower", "reject_blocking", "unsupported")
    }
    report = {
        "schema_version": RESULT_SCHEMA,
        "frozen_inputs": {
            "lowering_commit": ANCHOR_COMMIT,
            "corpus_sha256": CORPUS_SHA256,
            "mutant_oracles_sha256": MUTANT_ORACLES_SHA256,
            "tla_tools_jar_sha256": TLA_TOOLS_SHA256,
        },
        "toolchain": toolchain(jar),
        "summary": {
            "total": len(results),
            "oracle_defined": len(results),
            "executed": sum(result["executed"] for result in results),
            "rejected_observed": sum(not result["survived"] for result in results),
            "survivors": sum(result["survived"] for result in results),
            "artifacts_claimed": sum(
                result["artifacts_claimed"] for result in results
            ),
            "pre_lowering_rejections": sum(
                result["phase"] == "pre_lowering_semantic_gate"
                for result in results
            ),
            "dispositions": counts,
            "status": "pass" if all(not r["survived"] for r in results) else "fail",
        },
        "replay": {
            "command": (
                "python3 scripts/materialize_phase3b_mutants.py "
                "--corpus benchmarks/phase3b-corpus-v0.2.1 "
                "--tla-tools-jar \"$TLA_TOOLS_JAR\" "
                "--output \"$OUTPUT\""
            )
        },
        "results": results,
    }
    write_json(output_dir / "semantic-mutant-results.json", report)
    deterministic_files = {
        path.relative_to(output_dir).as_posix(): sha256_file(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "suite-manifest.json"
    }
    suite_manifest = {
        "schema_version": "phase4a-semantic-mutant-suite-manifest-0.2",
        "hash_algorithm": "sha256",
        "artifacts": deterministic_files,
    }
    write_json(output_dir / "suite-manifest.json", suite_manifest)
    return report


def recompute_projection(
    case: dict[str, Any], mutant_id: str
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    baseline = semantic_projection(case)
    mutated = copy.deepcopy(baseline)
    proof = apply_patches(mutated, MUTATIONS[mutant_id]["patches"])
    return baseline, mutated, proof


def _expected_lower_files(mutant_id: str) -> set[str]:
    module = {
        "mutant.17.submitted-is-settled": "Phase4aSubmittedIsSettled",
        "mutant.18.single-trace": "Phase4aSingleTrace",
    }[mutant_id]
    prefix = f"lower/{mutant_id}/"
    return {
        prefix + f"{module}.cfg",
        prefix + f"{module}.tla",
        prefix + "classification.json",
        prefix + "execution-evidence-manifest.json",
        prefix + "execution-report.json",
        prefix + "input.fsir.json",
        prefix + "manifest.json",
        prefix + "mapping-proof.json",
        prefix + "normalized-trace.json",
        prefix + "source-map.json",
        prefix + "tlc-output.txt",
    }


def _validate_exact_file_set(
    evidence_dir: Path, lower_ids: list[str]
) -> None:
    expected = {
        "semantic-mutant-results.json",
        "suite-manifest.json",
    }
    for mutant_id in lower_ids:
        expected.update(_expected_lower_files(mutant_id))
    observed = {
        path.relative_to(evidence_dir).as_posix()
        for path in evidence_dir.rglob("*")
        if path.is_file()
    }
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ValueError(
            f"evidence artifact set mismatch; missing={missing}, extra={extra}"
        )


def _validate_suite_manifest(evidence_dir: Path) -> None:
    manifest = load_json(evidence_dir / "suite-manifest.json")
    if set(manifest) != {"schema_version", "hash_algorithm", "artifacts"}:
        raise ValueError("suite manifest has unexpected fields")
    if (
        manifest["schema_version"]
        != "phase4a-semantic-mutant-suite-manifest-0.2"
        or manifest["hash_algorithm"] != "sha256"
    ):
        raise ValueError("suite manifest identity is invalid")
    expected_paths = {
        path.relative_to(evidence_dir).as_posix()
        for path in evidence_dir.rglob("*")
        if path.is_file() and path.name != "suite-manifest.json"
    }
    if set(manifest["artifacts"]) != expected_paths:
        raise ValueError("suite manifest does not cover the exact artifact set")
    for relative in sorted(expected_paths):
        if sha256_file(evidence_dir / relative) != manifest["artifacts"][relative]:
            raise ValueError(f"evidence hash mismatch: {relative}")


def _reconstruct_lowered(artifact_dir: Path, module_name: str) -> LoweredFsir:
    return LoweredFsir(
        module_name=module_name,
        tla_text=(artifact_dir / f"{module_name}.tla").read_text(
            encoding="utf-8"
        ),
        cfg_text=(artifact_dir / f"{module_name}.cfg").read_text(
            encoding="utf-8"
        ),
        source_map=load_json(artifact_dir / "source-map.json"),
        manifest=load_json(artifact_dir / "manifest.json"),
    )


def _validate_lower_backend(
    *,
    result: dict[str, Any],
    case: dict[str, Any],
    baseline_projection: dict[str, Any],
    mutated_projection: dict[str, Any],
    corpus_dir: Path,
    evidence_dir: Path,
    jar: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    mutant_id = result["mutant_id"]
    artifact_dir = evidence_dir / "lower" / mutant_id
    expected_input, expected_mapping = derive_lower_input(
        mutant_id=mutant_id,
        case=case,
        baseline_projection=baseline_projection,
        mutated_projection=mutated_projection,
        corpus_dir=corpus_dir,
    )
    if load_json(artifact_dir / "mapping-proof.json") != expected_mapping:
        raise ValueError(f"lower mapping proof drift: {mutant_id}")
    if load_json(artifact_dir / "input.fsir.json") != expected_input:
        raise ValueError(f"lower input is not projection-derived: {mutant_id}")
    document = FsirDocument(**expected_input)
    module_name = {
        "mutant.17.submitted-is-settled": "Phase4aSubmittedIsSettled",
        "mutant.18.single-trace": "Phase4aSingleTrace",
    }[mutant_id]
    lowered = _reconstruct_lowered(artifact_dir, module_name)
    regenerated = lower_fsir(document, module_name, tla_tools_jar=None)
    expected_manifest = copy.deepcopy(regenerated.manifest)
    expected_manifest["tools"]["tlc"] = {
        "identity": "tla2tools.jar",
        "sha256": TLA_TOOLS_SHA256,
    }
    if (
        lowered.tla_text != regenerated.tla_text
        or lowered.cfg_text != regenerated.cfg_text
        or lowered.source_map != regenerated.source_map
        or lowered.manifest != expected_manifest
    ):
        raise ValueError(f"lowered artifact regeneration drift: {mutant_id}")
    if jar is not None:
        verify_lowered_fsir(document, lowered, tla_tools_jar=jar)

    classification_raw = load_json(artifact_dir / "classification.json")
    if set(classification_raw) != {
        "kind",
        "returncode",
        "violated_property_ids",
        "detail",
    }:
        raise ValueError(f"classification fields drift: {mutant_id}")
    classification = TlcClassification(
        kind=classification_raw["kind"],
        returncode=classification_raw["returncode"],
        violated_property_ids=tuple(
            classification_raw["violated_property_ids"]
        ),
        detail=classification_raw["detail"],
    )
    tlc_output = (artifact_dir / "tlc-output.txt").read_text(
        encoding="utf-8"
    )
    if (
        classify_tlc_result(
            classification.returncode, tlc_output, lowered.source_map
        )
        != classification
    ):
        raise ValueError(f"TLC classification cannot be recomputed: {mutant_id}")
    trace = (
        normalize_tlc_counterexample(tlc_output, lowered.source_map)
        if classification.kind
        in {"property_violation", "temporal_violation"}
        else []
    )
    if load_json(artifact_dir / "normalized-trace.json") != trace:
        raise ValueError(f"normalized trace cannot be recomputed: {mutant_id}")
    expected_report = lower_execution_report(
        mutant_id=mutant_id,
        mapping_proof=expected_mapping,
        input_payload=expected_input,
        classification=classification,
        trace=trace,
    )
    if not expected_report["satisfied"]:
        raise ValueError(f"lower semantic oracle was not satisfied: {mutant_id}")
    if load_json(artifact_dir / "execution-report.json") != expected_report:
        raise ValueError(f"execution report cannot be recomputed: {mutant_id}")
    expected_execution_manifest = build_execution_evidence_manifest(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=expected_report,
    )
    if (
        load_json(artifact_dir / "execution-evidence-manifest.json")
        != expected_execution_manifest
    ):
        raise ValueError(f"execution manifest cannot be recomputed: {mutant_id}")
    verify_execution_evidence(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=expected_report,
        execution_manifest=expected_execution_manifest,
    )
    artifact_hashes = {
        path.relative_to(artifact_dir).as_posix(): sha256_file(path)
        for path in sorted(artifact_dir.iterdir())
        if path.is_file()
    }
    expected_backend = {
        "input_derivation": "projection_to_fsir_total_mapping",
        "base_fixture_id": expected_mapping["declared_mapping"][
            "base_fixture_id"
        ],
        "mapping_proof_sha256": sha256_json(expected_mapping),
        "input_fsir_sha256": sha256_json(expected_input),
        "module_name": module_name,
        "classification": classification.kind,
        "property_ids": list(classification.violated_property_ids),
        "event_ids": [item["event_id"] for item in trace],
        "returncode": classification.returncode,
        "artifact_hashes": artifact_hashes,
        "execution_evidence_manifest": expected_execution_manifest,
    }
    expected_semantic_oracle = {
        "tool": "approved_fsir_lowering_real_tlc_oracle",
        "observed": "rejected",
        "gate_code": MUTATIONS[mutant_id]["gate"],
        "classification": classification.kind,
        "property_ids": list(classification.violated_property_ids),
        "event_ids": [item["event_id"] for item in trace],
        "returncode": classification.returncode,
        "expected_gate_matched": True,
    }
    expected_rejection = {
        "class": "ExecutableSemanticOracleViolation",
        "gate_code": MUTATIONS[mutant_id]["gate"],
        "message": (
            f"executable semantic gate {MUTATIONS[mutant_id]['gate']} "
            f"rejected {mutant_id} after real TLC"
        ),
        "before_executable_artifacts": False,
    }
    return expected_backend, expected_semantic_oracle, expected_rejection


def validate_existing(
    corpus_dir: Path, evidence_dir: Path, jar: Path | None
) -> dict[str, Any]:
    verify_frozen_corpus(corpus_dir)
    verify_backend_anchor()
    if jar is not None and sha256_file(jar) != TLA_TOOLS_SHA256:
        raise ValueError("TLA+ tools jar does not match the approved hash")
    report = load_json(evidence_dir / "semantic-mutant-results.json")
    if set(report) != {
        "schema_version",
        "frozen_inputs",
        "toolchain",
        "summary",
        "replay",
        "results",
    } or report["schema_version"] != RESULT_SCHEMA:
        raise ValueError("unexpected materializer result schema")
    if report["frozen_inputs"] != {
        "lowering_commit": ANCHOR_COMMIT,
        "corpus_sha256": CORPUS_SHA256,
        "mutant_oracles_sha256": MUTANT_ORACLES_SHA256,
        "tla_tools_jar_sha256": TLA_TOOLS_SHA256,
    }:
        raise ValueError("frozen input identity drift")
    required_toolchain = {
        "python",
        "pydantic",
        "java",
        "tla_tools_jar_sha256",
        "lowerer_version",
        "source_map_version",
        "lowering_manifest_version",
        "execution_manifest_version",
    }
    if set(report["toolchain"]) != required_toolchain:
        raise ValueError("toolchain metadata is incomplete")
    if (
        report["toolchain"]["tla_tools_jar_sha256"] != TLA_TOOLS_SHA256
        or report["toolchain"]["lowerer_version"] != LOWERER_VERSION
        or report["toolchain"]["source_map_version"] != SOURCE_MAP_VERSION
        or report["toolchain"]["lowering_manifest_version"]
        != MANIFEST_VERSION
        or report["toolchain"]["execution_manifest_version"]
        != EXECUTION_MANIFEST_VERSION
        or any(not report["toolchain"][key] for key in required_toolchain)
    ):
        raise ValueError("toolchain identity drift")

    corpus = load_json(corpus_dir / "corpus.json")
    oracles = load_json(corpus_dir / "mutant-results.json")
    declared = corpus_mutants(corpus, oracles)
    expected_ids = [mutant["id"] for _, mutant, _ in declared]
    observed_ids = [result["mutant_id"] for result in report["results"]]
    if observed_ids != expected_ids:
        raise ValueError("result ordering/coverage differs from frozen corpus")
    lower_ids = [
        oracle["mutant_id"]
        for oracle in oracles["results"]
        if oracle["lowering_expectation"] == "lower"
    ]
    _validate_exact_file_set(evidence_dir, lower_ids)
    _validate_suite_manifest(evidence_dir)

    expected_summary = {
        "total": 32,
        "oracle_defined": 32,
        "executed": 32,
        "rejected_observed": 32,
        "survivors": 0,
        "artifacts_claimed": 2,
        "pre_lowering_rejections": 30,
        "dispositions": {
            "lower": 2,
            "reject_blocking": 10,
            "unsupported": 20,
        },
        "status": "pass",
    }
    if report["summary"] != expected_summary:
        raise ValueError("aggregate materializer counts are not exact")
    if report["replay"] != {
        "command": (
            "python3 scripts/materialize_phase3b_mutants.py "
            "--corpus benchmarks/phase3b-corpus-v0.2.1 "
            "--tla-tools-jar \"$TLA_TOOLS_JAR\" "
            "--output \"$OUTPUT\""
        )
    }:
        raise ValueError("replay command drift")

    for result, (case, mutant, oracle) in zip(
        report["results"], declared, strict=True
    ):
        mutant_id = mutant["id"]
        baseline, mutated, proof = recompute_projection(case, mutant_id)
        expected_core = {
            "case_id": case["id"],
            "mutant_id": mutant_id,
            "edit": mutant["edit"],
            "expected_gate": mutant["expected"],
            "semantic_gate_code": MUTATIONS[mutant_id]["gate"],
            "lowering_expectation": oracle["lowering_expectation"],
            "status": "executed_rejected",
            "executed": True,
            "survived": False,
            "baseline_projection_sha256": sha256_json(baseline),
            "mutated_projection_sha256": sha256_json(mutated),
            "mutation_proof": proof,
        }
        for key, expected in expected_core.items():
            if result.get(key) != expected:
                raise ValueError(f"recomputed result drift: {mutant_id}/{key}")
        if oracle["lowering_expectation"] == "lower":
            expected_backend, expected_semantic, expected_rejection = (
                _validate_lower_backend(
                    result=result,
                    case=case,
                    baseline_projection=baseline,
                    mutated_projection=mutated,
                    corpus_dir=corpus_dir,
                    evidence_dir=evidence_dir,
                    jar=jar,
                )
            )
            expected_phase = "post_tlc_semantic_oracle"
            expected_artifacts = True
        else:
            validate_semantic_projection(mutant_id, baseline, baseline)
            try:
                validate_semantic_projection(mutant_id, baseline, mutated)
            except SemanticOracleViolation as error:
                observed_error = error
            else:
                raise ValueError(
                    f"closed semantic oracle accepted {mutant_id}"
                )
            expected_backend = None
            expected_semantic = {
                "tool": semantic_oracle_tool_identity(),
                "input_sha256": sha256_json(mutated),
                "baseline_input_sha256": sha256_json(baseline),
                "observed": "rejected",
                "gate_code": observed_error.gate_code,
                "changed_paths": list(observed_error.changed_paths),
                "class": observed_error.__class__.__name__,
                "message": str(observed_error),
                "expected_gate_matched": observed_error.gate_code
                == MUTATIONS[mutant_id]["gate"],
            }
            expected_rejection = observed_error.to_json() | {
                "before_executable_artifacts": True
            }
            expected_phase = "pre_lowering_semantic_gate"
            expected_artifacts = False
        comparisons = {
            "phase": expected_phase,
            "artifacts_claimed": expected_artifacts,
            "semantic_oracle": expected_semantic,
            "rejection": expected_rejection,
            "backend": expected_backend,
        }
        for key, expected in comparisons.items():
            if result.get(key) != expected:
                raise ValueError(
                    f"independent outcome recomputation drift: "
                    f"{mutant_id}/{key}"
                )
        if set(result) != set(expected_core) | set(comparisons):
            raise ValueError(f"result field set drift: {mutant_id}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "benchmarks" / "phase3b-corpus-v0.2.1",
    )
    parser.add_argument("--tla-tools-jar", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-existing", type=Path)
    args = parser.parse_args()
    corpus_dir = args.corpus.resolve()
    if args.validate_existing:
        report = validate_existing(
            corpus_dir,
            args.validate_existing.resolve(),
            args.tla_tools_jar.resolve() if args.tla_tools_jar else None,
        )
    else:
        if not args.output or not args.tla_tools_jar:
            parser.error("--output and --tla-tools-jar are required for execution")
        report = materialize_all(
            corpus_dir,
            args.output.resolve(),
            args.tla_tools_jar.resolve(),
        )
    print(
        canonical_json(
            {
                "status": report["summary"]["status"],
                "executed": report["summary"]["executed"],
                "rejected_observed": report["summary"]["rejected_observed"],
                "survivors": report["summary"]["survivors"],
            }
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
