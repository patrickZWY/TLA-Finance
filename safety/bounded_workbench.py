"""Bounded FSIR workbench integration.

This module is deliberately separate from the legacy prose semantic-check
path.  It accepts either a closed FSIR v0.1 document or a frozen corpus case
identifier.  It never treats prose as FSIR and never falls back from invalid
FSIR to model extraction.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from safety.fsir import FsirDocument, dump_fsir
from safety.fsir_lowering import (
    LoweredFsir,
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
CORPUS_ROOT = ROOT / "fixtures" / "phase3b-corpus-v0.2.1"
CORPUS_PATH = CORPUS_ROOT / "corpus.json"
CORE30_REFERENCE_ROOT = (
    ROOT / "contracts" / "phase4b-core30-reference-audit-v0.1"
)
CORE30_REFERENCE_LINKS_PATH = CORE30_REFERENCE_ROOT / "reference-links.json"
CORE30_STAGE4_DECISION_PATH = (
    CORE30_REFERENCE_ROOT / "stage4-oracle-decision.json"
)
APPROVED_LOWERING_COMMIT = "d45efd09ffe5c77b89fcad1954d7959e54b7b8f3"
CORPUS_VERSION = "phase3b-corpus-0.2.1"
RESPONSE_VERSION = "bounded-workbench-0.1"
TLC_JAR_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
CORPUS_SHA256 = "0467b64d0148d06ed103353f4c91dc2b76ce4b45ac5b6c13412d1c8e8181c7ce"
CORE30_REFERENCE_LINKS_SHA256 = (
    "07184bbe7579d0d74d1727f8aac557ec82510504eee46426f6d156c9ae6104f3"
)
CORE30_STAGE4_DECISION_SHA256 = (
    "9c963534c269b91210a1c9e78c4ca22c48209ee6bae85c77d6171021f5ea4e17"
)
CORE30_REFERENCE_ARCHIVE_SHA256 = (
    "0a3088c02ecf07c2b198535f618bfe277a676716212b2b671f80f001a306ccdb"
)

CONTROL_KEYS = (
    "approve",
    "edit",
    "reject",
    "stop",
    "revise",
    "rerun",
    "clarify",
    "inspect_evidence",
    "resume",
    "new_goal",
    "verify",
)

STATE_CONTROLS: dict[str, dict[str, bool]] = {
    "clarification_required": {
        "edit": True,
        "stop": True,
        "clarify": True,
    },
    "ready_for_review": {
        "edit": True,
        "reject": True,
        "stop": True,
        "verify": True,
    },
    "verification_running": {
        "stop": True,
    },
    "violation_found": {
        "stop": True,
        "revise": True,
        "inspect_evidence": True,
    },
    "verification_unavailable": {
        "edit": True,
        "stop": True,
        "rerun": True,
    },
    "revision_proposed": {
        "edit": True,
        "reject": True,
        "stop": True,
    },
    "reverification_required": {
        "edit": True,
        "reject": True,
        "stop": True,
        "verify": True,
    },
    "checks_passed": {
        "edit": True,
        "stop": True,
        "inspect_evidence": True,
    },
    "bounded_approval_required": {
        "approve": True,
        "edit": True,
        "reject": True,
        "stop": True,
        "inspect_evidence": True,
    },
    "stopped": {
        "resume": True,
        "new_goal": True,
    },
}


def control_envelope(state: str) -> dict[str, bool]:
    """Return the closed control set for a product state."""

    enabled = STATE_CONTROLS.get(state, {})
    return {key: bool(enabled.get(key, False)) for key in CONTROL_KEYS}


def corpus_case_response(case_id: str, hero_stage: int | None = None) -> dict[str, Any]:
    """Return a frozen corpus projection with verified canonical evidence.

    Only the two corpus cases with ``lower`` disposition claim canonical
    lowering artifacts.  Unsupported and reject-blocking cases remain
    fail-closed.  Core 30 may replay its approved eight-stage hero sequence.
    """

    corpus_bytes = CORPUS_PATH.read_bytes()
    if _sha256_bytes(corpus_bytes) != CORPUS_SHA256:
        raise ValueError("frozen corpus hash drift")
    corpus = json.loads(corpus_bytes)
    case = next((item for item in corpus["cases"] if item["id"] == case_id), None)
    if case is None:
        raise KeyError(f"unknown frozen corpus case: {case_id}")

    projection = case["product_projection"]
    lowering_oracle = case["lowering_oracle"]
    stage = None
    if hero_stage is not None:
        if case_id != "core.30":
            raise ValueError("hero_stage is supported only for core.30")
        stage = next(
            (item for item in case.get("hero_stages", []) if item["stage"] == hero_stage),
            None,
        )
        if stage is None:
            raise ValueError("hero_stage must be an integer from 1 through 8")

    state = stage["state"] if stage else projection["agent_phase"]
    controls = (
        dict(stage["projection_snapshot"]["controls"])
        if stage
        else dict(projection["controls"])
    )
    _require_closed_controls(state, controls)

    fixture_mode = _fixture_mode(case, stage)
    canonical = _verified_fixture(fixture_mode) if fixture_mode else None
    response = _base_response(
        state=state,
        controls=controls,
        source_kind="corpus_case",
        case_id=case_id,
    )
    response.update(
        {
            "corpus": {
                "version": corpus["corpus_version"],
                "semantic_projection_version": corpus["semantic_projection_version"],
                "approved_lowering_commit": APPROVED_LOWERING_COMMIT,
            },
            "goal": {
                "user": projection["user_goal"],
                "agent": projection["agent_goal"],
            },
            "projection": _projection_payload(case, stage),
            "lowering": {
                "disposition": lowering_oracle["expectation"],
                "reason_code": lowering_oracle["reason_code"],
                "emits_artifacts": lowering_oracle["emits_artifacts"],
                "approved_commit": lowering_oracle["frozen_commit"],
                "fixture_id": lowering_oracle.get("fixture_id"),
                "fail_closed": lowering_oracle["expectation"] != "lower",
            },
        }
    )

    if canonical and case_id != "core.30":
        response["fsir"] = canonical["fsir"]
        response["source_map"] = canonical["source_map"]
        response["verification"] = canonical["verification"]
        response["counterexample"] = canonical["counterexample"]
        response["evidence"] = canonical["evidence"]
        response["lowering"].update(
            {
                "disposition": "lower",
                "reason_code": None,
                "emits_artifacts": True,
                "fixture_id": (
                    "fixture.phase3a.lifecycle.concurrent"
                    if fixture_mode == "concurrent"
                    else "fixture.phase3a.lifecycle.ordered"
                ),
                "fail_closed": False,
            }
        )
    else:
        response["fsir"] = _projected_fsir(case, stage)
        response["verification"] = _projected_verification(case, stage)
        response["counterexample"] = projection["counterexample"]
        response["evidence"] = {
            "status": (
                stage["projection_snapshot"]["evidence_status"]
                if stage
                else "none"
            ),
            "trusted": False,
            "artifact_hashes": {},
            "reason": "No canonical lowering artifact is claimed for this state.",
        }

    if canonical and case_id == "core.30":
        reference_link, stage4_decision = _core30_reference_contract(
            fixture_mode, canonical
        )
        response["reference_evidence"] = {
            **canonical,
            "evidence_applicability": "reference_only",
            "contract_match": False,
            "fixture_only": True,
            "reason_code": "hero_fixture_contract_unmapped",
            "fixture_case_id": (
                "core.18" if fixture_mode == "concurrent" else "core.17"
            ),
            "fixture_id": (
                "fixture.phase3a.lifecycle.concurrent"
                if fixture_mode == "concurrent"
                else "fixture.phase3a.lifecycle.ordered"
            ),
            "verdict_scope": "fixture_only",
            "event_id_scope": "fixture_only",
            "reference_link": reference_link,
            "stage4_oracle_decision": stage4_decision,
            "audit": {
                "source_archive_sha256": CORE30_REFERENCE_ARCHIVE_SHA256,
                "reference_links_sha256": CORE30_REFERENCE_LINKS_SHA256,
                "stage4_oracle_decision_sha256": (
                    CORE30_STAGE4_DECISION_SHA256
                ),
                "corpus_evidence": False,
            },
        }
        mismatch_messages = {
            "source_document_mismatch": (
                "core.30 and the lifecycle fixture bind different source documents"
            ),
            "source_span_mismatch": (
                "core.30 source spans have no total mapping to fixture spans"
            ),
            "fsir_document_id_mismatch": (
                "core.30 and the lifecycle fixture use different FSIR document IDs"
            ),
            "action_granularity_mismatch": (
                "three core.30 business action IDs are not a total map to six "
                "lifecycle event IDs"
            ),
            "property_contract_mismatch": (
                "no_rejected_action is not implemented by the fixture; only "
                "no_negative_cash has a reference-only correspondence"
            ),
            "bounds_mismatch": (
                "core.30 max_steps=5 differs from the fixture max_steps=6"
            ),
        }
        response["integration_compatibility"] = {
            "status": "blocked",
            "contract_match": False,
            "approval_authorized": False,
            "reason_code": "hero_fixture_contract_unmapped",
            "mismatches": [
                {
                    "code": code,
                    "message": mismatch_messages[code],
                }
                for code in reference_link["mismatch_reason_codes"]
            ],
            "reference_property_mapping": {
                stage4_decision["chosen_semantic_property_id"]: (
                    stage4_decision["chosen_backend_property_id"]
                )
            },
            "unsupported_projection_property_ids": [
                stage4_decision["unsupported_property"]["id"]
            ],
            "business_node_count": 3,
            "verified_fixture_step_bound": reference_link["fixture"]["bounds"][
                "max_steps"
            ],
        }
        response["lowering"] = {
            "disposition": "reject_blocking",
            "reason_code": "hero_fixture_contract_unmapped",
            "emits_artifacts": False,
            "approved_commit": APPROVED_LOWERING_COMMIT,
            "fixture_id": None,
            "fail_closed": True,
        }
        response["agent"] = {
            "state": "verification_unavailable",
            "controls": control_envelope("verification_unavailable"),
        }
        response["decision"] = "verification_unavailable"
        response["verification"].update(
            {
                "status": "infrastructure_failure",
                "classification": "infrastructure_failure",
                "reason_code": "hero_fixture_contract_unmapped",
                "message": (
                    "The referenced lifecycle evidence is not proven to apply "
                    "to this hero projection."
                ),
                "fsir_hash": None,
                "source_document_hash": None,
                "policy_hash": None,
                "model_hash": None,
                "config_hash": None,
                "source_map_hash": None,
                "violated_property_ids": [],
            }
        )
        response["counterexample"] = {
            "summary": (
                "No core.30 counterexample is asserted. The lifecycle trace "
                "is fixture-only reference data."
            ),
            "first_violating_state": None,
            "violated_property_ids": [],
            "path": [],
        }
        response["evidence"] = {
            "status": "none",
            "trusted": False,
            "artifact_hashes": {},
            "reason": (
                "Canonical lifecycle evidence is available only as a separate "
                "reference run; it cannot verify core.30."
            ),
            "freshness": None,
        }
        response["core30_derived"] = {
            **reference_link["derived_core30"],
            "fsir_hash": None,
            "model_hash": None,
            "config_hash": None,
            "source_map_hash": None,
            "approval_scope": None,
        }

    if case_id == "core.06":
        response["decision"] = "no_action"
        response["fsir"]["intent"] = "no_action"
        response["verification"].update(
            {
                "status": "complete",
                "classification": "not_applicable",
                "message": (
                    "The validated intent contains no financial action. "
                    "No execution approval is offered."
                ),
            }
        )
        response["evidence"] = {
            "status": "not_applicable",
            "trusted": True,
            "artifact_hashes": {},
            "reason": "No action exists to lower or execute.",
        }

    if stage:
        snapshot = stage["projection_snapshot"]
        if case_id != "core.30":
            _mask_unavailable_hero_evidence(response, stage)
        response["hero"] = {
            "stage": stage["stage"],
            "total_stages": 8,
            "label": stage["label"],
            "required_output": stage["required_output"],
            "snapshot": (
                _sanitized_core30_snapshot(snapshot)
                if case_id == "core.30"
                else snapshot
            ),
        }
        if snapshot.get("stale_evidence"):
            response["evidence"]["status"] = "stale"
            response["evidence"]["trusted"] = False
            response["evidence"]["stale"] = snapshot["stale_evidence"]
        if stage["stage"] in {5, 6}:
            response["revision"] = snapshot.get("revision")

    return response


def _sanitized_core30_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(snapshot)
    sanitized["config_hash"] = None
    sanitized["model_hash"] = None
    sanitized["evidence_status"] = "unavailable"
    sanitized["approval_scope"] = None
    if sanitized.get("counterexample"):
        sanitized["counterexample"] = {
            "evidence_applicability": "reference_only",
            "fixture_id": sanitized["counterexample"].get("fixture_id"),
        }
    return sanitized


def _mask_unavailable_hero_evidence(
    response: dict[str, Any],
    stage: dict[str, Any],
) -> None:
    """Keep later fixture evidence out of stages where it is not yet current."""

    stage_number = stage["stage"]
    if stage_number in {1, 4, 7, 8}:
        return
    snapshot = stage["projection_snapshot"]
    response["verification"].update(
        {
            "status": snapshot["verification_status"],
            "classification": None,
            "returncode": None,
            "violated_property_ids": [],
            "message": None,
            "model_hash": snapshot.get("model_hash"),
            "config_hash": snapshot.get("config_hash"),
        }
    )
    for prop in response["verification"].get("properties", []):
        prop["status"] = "not_checked"
    response["counterexample"] = {
        "summary": "No current counterexample is asserted for this stage.",
        "first_violating_state": None,
        "violated_property_ids": [],
        "path": [],
    }
    status = snapshot["evidence_status"]
    response["evidence"] = {
        "status": status,
        "trusted": False,
        "artifact_hashes": {},
        "reason": {
            "none": "Verification evidence does not exist for this stage.",
            "pending": "Verification is running; no verdict is available yet.",
            "stale": "Prior evidence is stale for the revised FSIR.",
        }.get(status, "No current evidence is available."),
    }


def _core30_reference_contract(
    mode: str,
    canonical: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and cross-check the independently accepted reference-only oracle."""

    if mode not in {"concurrent", "ordered"}:
        raise ValueError("core.30 reference mode is not closed")
    links_bytes = CORE30_REFERENCE_LINKS_PATH.read_bytes()
    decision_bytes = CORE30_STAGE4_DECISION_PATH.read_bytes()
    if _sha256_bytes(links_bytes) != CORE30_REFERENCE_LINKS_SHA256:
        raise ValueError("core.30 reference-link contract hash drift")
    if _sha256_bytes(decision_bytes) != CORE30_STAGE4_DECISION_SHA256:
        raise ValueError("core.30 stage-4 decision hash drift")

    contract = json.loads(links_bytes)
    decision = json.loads(decision_bytes)
    fixture_id = f"fixture.phase3a.lifecycle.{mode}"
    link = next(
        (
            item
            for item in contract["links"]
            if item["fixture"]["fixture_id"] == fixture_id
        ),
        None,
    )
    if link is None:
        raise ValueError(f"core.30 reference link missing for {fixture_id}")

    verification = canonical["verification"]
    evidence = canonical["evidence"]
    fixture = link["fixture"]
    actual_hashes = {
        "fsir_canonical_json_sha256": verification["fsir_hash"],
        "source_document_sha256": verification["source_document_hash"],
        "policy_snapshot_sha256": verification["policy_hash"],
        "lowering_manifest_sha256": evidence["artifact_hashes"][
            "lowering_manifest"
        ],
        "execution_evidence_manifest_sha256": evidence[
            "execution_evidence_manifest_sha256"
        ],
        "model_sha256": verification["model_hash"],
        "config_sha256": verification["config_hash"],
        "source_map_sha256": verification["source_map_hash"],
    }
    for name, actual in actual_hashes.items():
        if fixture[name] != actual:
            raise ValueError(f"core.30 reference {name} drift")
    if fixture["fsir_document_id"] != canonical["fsir"]["document_id"]:
        raise ValueError("core.30 reference FSIR document ID drift")
    if link["fixture_display"]["verdict"] != verification["classification"]:
        raise ValueError("core.30 reference fixture verdict drift")

    event_ids = [
        item["event_id"]
        for item in canonical["counterexample"].get("path", [])
        if item.get("event_id")
    ]
    if event_ids != link["fixture_display"]["event_ids"]:
        raise ValueError("core.30 reference counterexample event drift")
    violated = verification["violated_property_ids"]
    expected_property = link["fixture_display"]["violated_property_id"]
    if violated != ([expected_property] if expected_property else []):
        raise ValueError("core.30 reference property verdict drift")

    expected_bounds = fixture["bounds"]
    actual_bounds = canonical["fsir"]["bounds"]
    actual_domain = actual_bounds["domains"][0]["values"]
    if {
        "max_steps": actual_bounds["max_steps"],
        "max_actions": actual_bounds["max_actions"],
        "max_retries": actual_bounds["max_retries"],
        "time_horizon": actual_bounds["time_horizon"],
        "amount_domain": actual_domain,
    } != expected_bounds:
        raise ValueError("core.30 reference bounds drift")

    return deepcopy(link), deepcopy(decision)


def canonical_fsir_response(
    raw_fsir: dict[str, Any],
    *,
    run_model_checker: bool,
) -> dict[str, Any]:
    """Validate, lower, and optionally run TLC for a canonical FSIR document."""

    document = FsirDocument(**raw_fsir)
    document_digest = hashlib.sha256(
        _canonical_payload(dump_fsir(document)).encode("utf-8")
    ).hexdigest()
    module_name = f"FsirWorkbench{document_digest[:12].upper()}"
    jar = _configured_tlc_jar()

    try:
        lowered = lower_fsir(document, module_name, tla_tools_jar=jar)
        verify_lowered_fsir(document, lowered, tla_tools_jar=jar)
    except UnsupportedFsirError as exc:
        return _unsupported_document_response(document, "unsupported_fsir", str(exc))
    except ValueError as exc:
        reason = (
            "blocking_unresolved"
            if any(item.blocking for item in document.unresolved)
            else "invalid_bounded_semantics"
        )
        return _unsupported_document_response(document, reason, str(exc))

    base = _base_response(
        state="ready_for_review",
        controls=control_envelope("ready_for_review"),
        source_kind="canonical_fsir",
    )
    base.update(
        {
            "decision": "lowered_not_checked",
            "goal": {"user": "", "agent": "Review the canonical FSIR and bounded evidence."},
            "fsir": _fsir_presentation(document),
            "source_map": lowered.source_map,
            "lowering": {
                "disposition": "lower",
                "reason_code": None,
                "emits_artifacts": True,
                "approved_commit": APPROVED_LOWERING_COMMIT,
                "fixture_id": None,
                "fail_closed": False,
            },
            "verification": _verification_payload(
                document=document,
                lowered=lowered,
                classification=None,
            ),
            "counterexample": {
                "summary": "No counterexample is asserted.",
                "first_violating_state": None,
                "path": [],
            },
            "evidence": {
                "status": "none",
                "trusted": False,
                "artifact_hashes": {},
                "reason": "TLC was not requested.",
            },
        }
    )
    if not run_model_checker:
        return base
    if jar is None:
        base["agent"] = {
            "state": "verification_unavailable",
            "controls": control_envelope("verification_unavailable"),
        }
        base["decision"] = "verification_unavailable"
        base["verification"].update(
            {
                "status": "infrastructure_failure",
                "classification": "infrastructure_failure",
                "reason_code": "tlc_tools_unavailable",
                "message": "TLA_TOOLS_JAR is not configured with the approved jar.",
            }
        )
        base["evidence"]["reason"] = "TLC tools are unavailable."
        return base

    return _execute_canonical(document, lowered, jar, base)


def _execute_canonical(
    document: FsirDocument,
    lowered: LoweredFsir,
    jar: Path,
    response: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tla-finance-bounded-") as directory:
        artifact_dir = Path(directory)
        write_lowered_fsir(lowered, artifact_dir)
        try:
            completed = subprocess.run(
                [
                    "java",
                    "-cp",
                    str(jar),
                    "tlc2.TLC",
                    "-config",
                    f"{lowered.module_name}.cfg",
                    f"{lowered.module_name}.tla",
                ],
                cwd=artifact_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return _infrastructure_response(
                response,
                "tlc_timeout",
                "TLC exceeded the bounded 60 second timeout.",
            )
        except OSError:
            return _infrastructure_response(
                response,
                "tlc_launch_failed",
                "The approved TLC process could not be started.",
            )
    tlc_output = completed.stdout + completed.stderr
    classification = classify_tlc_result(
        completed.returncode,
        tlc_output,
        lowered.source_map,
    )
    try:
        trace = (
            normalize_tlc_counterexample(tlc_output, lowered.source_map)
            if classification.kind in {"property_violation", "temporal_violation"}
            else []
        )
    except ValueError:
        return _infrastructure_response(
            response,
            "trace_normalization_failed",
            "TLC reported a violation, but its strict normalized trace was invalid.",
        )
    execution_report = {
        "schema_version": "fsir-tla-execution-report-0.1",
        "module_name": lowered.module_name,
        "observed_classification": classification.kind,
        "observed_property_ids": list(classification.violated_property_ids),
        "normalized_trace_steps": len(trace),
    }
    evidence_manifest = build_execution_evidence_manifest(
        lowered=lowered,
        tlc_output=tlc_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=execution_report,
    )
    try:
        verify_execution_evidence(
            lowered=lowered,
            tlc_output=tlc_output,
            normalized_trace=trace,
            classification=classification,
            execution_report=execution_report,
            execution_manifest=evidence_manifest,
        )
    except ValueError:
        return _infrastructure_response(
            response,
            "evidence_integrity_failed",
            "Execution evidence failed its integrity contract.",
        )
    state = {
        "passed": "checks_passed",
        "property_violation": "violation_found",
        "temporal_violation": "violation_found",
        "infrastructure_failure": "verification_unavailable",
    }[classification.kind]
    response["agent"] = {"state": state, "controls": control_envelope(state)}
    response["decision"] = classification.kind
    response["verification"] = _verification_payload(
        document=document,
        lowered=lowered,
        classification=classification,
    )
    response["counterexample"] = _counterexample_payload(
        trace, classification.violated_property_ids
    )
    response["evidence"] = {
        "status": (
            "fresh"
            if classification.kind != "infrastructure_failure"
            else "unavailable"
        ),
        "trusted": classification.kind != "infrastructure_failure",
        "artifact_hashes": evidence_manifest["artifacts"],
        "manifest_schema": evidence_manifest["schema_version"],
        "reason": (
            None
            if classification.kind != "infrastructure_failure"
            else classification.detail
        ),
    }
    return response


def _infrastructure_response(
    response: dict[str, Any],
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    response["agent"] = {
        "state": "verification_unavailable",
        "controls": control_envelope("verification_unavailable"),
    }
    response["decision"] = "infrastructure_failure"
    response["verification"].update(
        {
            "status": "infrastructure_failure",
            "classification": "infrastructure_failure",
            "returncode": None,
            "violated_property_ids": [],
            "reason_code": reason_code,
            "message": message,
        }
    )
    for prop in response["verification"].get("properties", []):
        prop["status"] = "not_checked"
    response["counterexample"] = {
        "summary": "No trustworthy counterexample is available.",
        "first_violating_state": None,
        "violated_property_ids": [],
        "path": [],
    }
    response["evidence"] = {
        "status": "unavailable",
        "trusted": False,
        "artifact_hashes": {},
        "reason": message,
    }
    return response


def _verified_fixture(mode: str) -> dict[str, Any]:
    fixture_root = CORPUS_ROOT / "backend-artifacts" / mode
    raw_fsir = _load_json(fixture_root / "input.fsir.json")
    document = FsirDocument(**raw_fsir)
    manifest = _load_json(fixture_root / "manifest.json")
    source_map = _load_json(fixture_root / "source-map.json")
    tla_path = next(fixture_root.glob("*.tla"))
    cfg_path = next(fixture_root.glob("*.cfg"))
    lowered = LoweredFsir(
        module_name=manifest["module_name"],
        tla_text=tla_path.read_text(encoding="utf-8"),
        cfg_text=cfg_path.read_text(encoding="utf-8"),
        source_map=source_map,
        manifest=manifest,
    )
    _verify_fixture_artifact_hashes(document, lowered)

    raw_output = (fixture_root / "tlc-output.txt").read_text(encoding="utf-8")
    classification_raw = _load_json(fixture_root / "classification.json")
    classification = TlcClassification(
        kind=classification_raw["kind"],
        returncode=classification_raw["returncode"],
        violated_property_ids=tuple(classification_raw["violated_property_ids"]),
        detail=classification_raw["detail"],
    )
    actual_classification = classify_tlc_result(
        classification.returncode,
        raw_output,
        source_map,
    )
    if actual_classification != classification:
        raise ValueError(f"{mode} fixture classification drift")
    trace = _load_json(fixture_root / "normalized-trace.json")
    if classification.kind in {"property_violation", "temporal_violation"}:
        if normalize_tlc_counterexample(raw_output, source_map) != trace:
            raise ValueError(f"{mode} fixture normalized trace drift")
    elif trace:
        raise ValueError(f"{mode} passing fixture unexpectedly contains a trace")
    execution_report = _load_json(fixture_root / "execution-report.json")
    execution_manifest = _load_json(
        fixture_root / "execution-evidence-manifest.json"
    )
    execution_manifest_sha256 = _sha256_bytes(
        (fixture_root / "execution-evidence-manifest.json").read_bytes()
    )
    verify_execution_evidence(
        lowered=lowered,
        tlc_output=raw_output,
        normalized_trace=trace,
        classification=classification,
        execution_report=execution_report,
        execution_manifest=execution_manifest,
    )
    return {
        "fsir": _fsir_presentation(document),
        "source_map": source_map,
        "verification": _verification_payload(
            document=document,
            lowered=lowered,
            classification=classification,
        ),
        "counterexample": _counterexample_payload(
            trace, classification.violated_property_ids
        ),
        "evidence": {
            "status": "fresh",
            "trusted": True,
            "fixture_mode": mode,
            "manifest_schema": execution_manifest["schema_version"],
            "execution_evidence_manifest_sha256": (
                execution_manifest_sha256
            ),
            "artifact_hashes": execution_manifest["artifacts"],
        },
    }


def _verify_fixture_artifact_hashes(
    document: FsirDocument,
    lowered: LoweredFsir,
) -> None:
    expected = lowered.manifest
    hashes = {
        "fsir_canonical_json": _sha256(_canonical_payload(dump_fsir(document))),
        "model": _sha256(lowered.tla_text),
        "config": _sha256(lowered.cfg_text),
        "source_map": _sha256(_canonical_json(lowered.source_map)),
    }
    if hashes["fsir_canonical_json"] != expected["inputs"]["fsir_canonical_json"]:
        raise ValueError("fixture FSIR hash drift")
    for name in ("model", "config", "source_map"):
        if hashes[name] != expected["outputs"][name]:
            raise ValueError(f"fixture {name} hash drift")
    if expected["tools"]["tlc"]["sha256"] != TLC_JAR_SHA256:
        raise ValueError("fixture TLC identity is not the approved tool hash")


def _fsir_presentation(document: FsirDocument) -> dict[str, Any]:
    raw = dump_fsir(document)
    spans = {item["id"]: item for item in raw["provenance"]["spans"]}
    nodes = []
    for action in raw["actions"]:
        parameters = {item["name"]: item.get("value") for item in action["parameters"]}
        nodes.append(
            {
                "id": action["id"],
                "type": action["kind"],
                "actor_id": action["actor_id"],
                "label": _action_label(action, parameters),
                "fields": parameters,
                "source_span_ids": action["source_span_ids"],
                "source_spans": [
                    spans[span_id]
                    for span_id in action["source_span_ids"]
                    if span_id in spans
                ],
                "review_status": "pending",
            }
        )
    return {
        "canonical": True,
        "document_id": raw["meta"]["id"],
        "version": raw["meta"]["schema_version"],
        "intent": raw["meta"]["intent"],
        "source_document_sha256": raw["meta"]["source_document_sha256"],
        "source_spans": list(spans.values()),
        "nodes": nodes,
        "control": raw["control"],
        "assumptions": [
            {
                "id": item["id"],
                "kind": item["kind"],
                "source_span_ids": item["source_span_ids"],
            }
            for item in raw["assumptions"]
        ],
        "properties": [
            {
                "id": item["id"],
                "kind": item["kind"],
                "finding_code": item.get("finding_code"),
                "source_span_ids": item["source_span_ids"],
                "status": "not_checked",
            }
            for item in raw["properties"]
        ],
        "bounds": raw["bounds"],
        "unresolved": raw["unresolved"],
        "approval_scope": {
            "action_ids": [item["id"] for item in raw["actions"]],
            "max_actions": raw["bounds"]["max_actions"],
            "max_steps": raw["bounds"]["max_steps"],
            "max_retries": raw["bounds"]["max_retries"],
            "time_horizon": raw["bounds"]["time_horizon"],
            "expires_at": "must-be-selected-before-execution",
        },
    }


def _verification_payload(
    *,
    document: FsirDocument,
    lowered: LoweredFsir,
    classification: TlcClassification | None,
) -> dict[str, Any]:
    violated = set(classification.violated_property_ids if classification else ())
    mapped_ids = {
        item["fsir_property_id"]
        for item in lowered.source_map["properties"].values()
    }
    properties = []
    for prop in document.properties:
        if prop.id in violated:
            status = "violated"
        elif (
            classification is not None
            and classification.kind == "passed"
            and prop.id in mapped_ids
        ):
            status = "checked_pass"
        else:
            status = "not_checked"
        properties.append(
            {
                "id": prop.id,
                "kind": prop.kind,
                "finding_code": prop.finding_code,
                "source_span_ids": list(prop.source_span_ids),
                "status": status,
            }
        )
    return {
        "status": (
            "not_run" if classification is None else classification.kind
        ),
        "classification": (
            None if classification is None else classification.kind
        ),
        "returncode": (
            None if classification is None else classification.returncode
        ),
        "violated_property_ids": (
            [] if classification is None else list(classification.violated_property_ids)
        ),
        "message": None if classification is None else classification.detail,
        "reason_code": None,
        "backend": "TLC",
        "source_map_version": lowered.source_map["schema_version"],
        "lowering_manifest_version": lowered.manifest["schema_version"],
        "fsir_hash": lowered.manifest["inputs"]["fsir_canonical_json"],
        "source_document_hash": lowered.manifest["inputs"]["source_document"],
        "policy_hash": lowered.manifest["inputs"]["policy_snapshot"],
        "model_hash": lowered.manifest["outputs"]["model"],
        "config_hash": lowered.manifest["outputs"]["config"],
        "source_map_hash": lowered.manifest["outputs"]["source_map"],
        "tools": lowered.manifest["tools"],
        "properties": properties,
    }


def _counterexample_payload(
    trace: list[dict[str, Any]],
    property_ids: tuple[str, ...],
) -> dict[str, Any]:
    if not trace:
        return {
            "summary": "No counterexample is asserted.",
            "first_violating_state": None,
            "violated_property_ids": [],
            "path": [],
        }
    path = [
        {
            "state_id": "trace-state.0",
            "event_id": None,
            "operator_id": None,
            "before": trace[0]["before"],
            "after": trace[0]["before"],
            "violations": [],
        }
    ]
    for index, item in enumerate(trace, start=1):
        path.append(
            {
                "state_id": f"trace-state.{index}",
                "event_id": item["event_id"],
                "operator_id": item["operator_id"],
                "before": item["before"],
                "after": item["after"],
                "violations": list(property_ids) if index == len(trace) else [],
            }
        )
    return {
        "summary": (
            f"{', '.join(property_ids)} is violated at "
            f"{trace[-1]['event_id']}."
        ),
        "first_violating_state": path[-1]["state_id"],
        "violated_property_ids": list(property_ids),
        "path": path,
    }


def _unsupported_document_response(
    document: FsirDocument,
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    state = (
        "clarification_required"
        if reason_code == "blocking_unresolved"
        else "verification_unavailable"
    )
    response = _base_response(
        state=state,
        controls=control_envelope(state),
        source_kind="canonical_fsir",
    )
    response.update(
        {
            "decision": "reject_blocking" if state == "clarification_required" else "unsupported",
            "fsir": _fsir_presentation(document),
            "lowering": {
                "disposition": (
                    "reject_blocking"
                    if state == "clarification_required"
                    else "unsupported"
                ),
                "reason_code": reason_code,
                "emits_artifacts": False,
                "approved_commit": APPROVED_LOWERING_COMMIT,
                "fixture_id": None,
                "fail_closed": True,
            },
            "verification": {
                "status": "not_run",
                "classification": None,
                "reason_code": reason_code,
                "message": message,
                "properties": [],
            },
            "counterexample": {
                "summary": "No counterexample is asserted.",
                "first_violating_state": None,
                "path": [],
            },
            "evidence": {
                "status": "none",
                "trusted": False,
                "artifact_hashes": {},
                "reason": message,
            },
        }
    )
    return response


def _projected_fsir(case: dict[str, Any], stage: dict[str, Any] | None) -> dict[str, Any]:
    projection = case["product_projection"]
    return {
        "canonical": False,
        "document_id": projection["fsir_version"],
        "version": projection["fsir_version"],
        "intent": case["expected_semantics"]["intent"],
        "status": (
            stage["projection_snapshot"]["fsir_status"]
            if stage
            else projection["fsir_status"]
        ),
        "source_spans": case["source_spans"],
        "nodes": projection["nodes"],
        "assumptions": projection["assumptions"],
        "properties": projection["properties"],
        "bounds": projection["bounds"],
        "unresolved": case["expected_semantics"]["unresolved"],
        "approval_scope": projection["approval_scope"],
    }


def _projected_verification(
    case: dict[str, Any],
    stage: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = case["product_projection"]
    snapshot = stage["projection_snapshot"] if stage else None
    return {
        "status": (
            snapshot["verification_status"]
            if snapshot
            else projection["verification"]["status"]
        ),
        "classification": None,
        "reason_code": case["lowering_oracle"]["reason_code"],
        "message": (
            "Fail closed: canonical lowering evidence is not available for this projection."
        ),
        "backend": "not_run",
        "fsir_hash": None,
        "model_hash": snapshot.get("model_hash") if snapshot else None,
        "config_hash": snapshot.get("config_hash") if snapshot else None,
        "properties": projection["properties"],
    }


def _projection_payload(
    case: dict[str, Any],
    stage: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = case["product_projection"]
    return {
        "case_id": case["id"],
        "title": case["title"],
        "source_text": projection["source_text"],
        "source_spans": case["source_spans"],
        "questions": projection["questions"],
        "findings": projection["findings"],
        "revision": projection["revision"],
        "next_step": projection["agent_next_step"],
        "snapshot": (
            _sanitized_core30_snapshot(stage["projection_snapshot"])
            if stage and case["id"] == "core.30"
            else stage["projection_snapshot"] if stage else None
        ),
    }


def _fixture_mode(
    case: dict[str, Any],
    stage: dict[str, Any] | None,
) -> str | None:
    if stage:
        if stage["stage"] in {2, 3, 4}:
            return "concurrent"
        if stage["stage"] in {5, 6, 7, 8}:
            return "ordered"
        return None
    fixture_id = case["lowering_oracle"].get("fixture_id")
    if fixture_id == "fixture.phase3a.lifecycle.ordered":
        return "ordered"
    if fixture_id == "fixture.phase3a.lifecycle.concurrent":
        return "concurrent"
    return None


def _require_closed_controls(state: str, controls: dict[str, Any]) -> None:
    if set(controls) != set(CONTROL_KEYS):
        raise ValueError(f"{state} control envelope is not closed")
    expected = control_envelope(state)
    if controls != expected:
        raise ValueError(f"{state} control envelope does not match the approved matrix")


def _base_response(
    *,
    state: str,
    controls: dict[str, bool],
    source_kind: str,
    case_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RESPONSE_VERSION,
        "source_kind": source_kind,
        "case_id": case_id,
        "decision": "pending",
        "agent": {"state": state, "controls": controls},
    }


def _configured_tlc_jar() -> Path | None:
    configured = os.getenv("TLA_TOOLS_JAR", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or _sha256_bytes(path.read_bytes()) != TLC_JAR_SHA256:
        return None
    return path


def _action_label(action: dict[str, Any], parameters: dict[str, Any]) -> str:
    verb = str(parameters.get("kind") or action["kind"]).replace("_", " ")
    amount = parameters.get("amount")
    route = ""
    if parameters.get("source") or parameters.get("destination"):
        route = f" · {parameters.get('source', '?')} → {parameters.get('destination', '?')}"
    return f"{verb.title()}{f' ${amount}' if amount is not None else ''}{route}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return _canonical_payload(value) + "\n"


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "APPROVED_LOWERING_COMMIT",
    "CORPUS_VERSION",
    "RESPONSE_VERSION",
    "STATE_CONTROLS",
    "canonical_fsir_response",
    "control_envelope",
    "corpus_case_response",
]
