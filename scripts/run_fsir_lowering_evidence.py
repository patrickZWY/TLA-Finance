#!/usr/bin/env python3
"""Generate reproducible FSIR lowering/TLC evidence for independent review."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from safety.fsir import FsirDocument
from safety.fsir_lowering import (
    UnsupportedFsirError,
    build_execution_evidence_manifest,
    classify_tlc_result,
    lower_fsir,
    normalize_tlc_counterexample,
    verify_execution_evidence,
    verify_lowered_fsir,
    write_lowered_fsir,
)
from tests.test_fsir_lowering import lifecycle_document


ROOT = Path(__file__).resolve().parents[1]


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def run_tlc(artifact_dir, module_name, jar):
    completed = subprocess.run(
        [
            "java",
            "-cp",
            str(jar),
            "tlc2.TLC",
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
    return completed, completed.stdout + completed.stderr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tla-tools-jar", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    jar = args.tla_tools_jar.resolve()
    if not jar.is_file():
        raise SystemExit(f"TLA+ tools jar not found: {jar}")
    output.mkdir(parents=True, exist_ok=True)

    cases = {}
    lowered_by_mode = {}
    execution_records = {}
    all_ok = True
    for mode, control, expected, expected_property_ids in (
        ("ordered", "sequence", "passed", []),
        (
            "concurrent",
            "partial_order",
            "property_violation",
            [
                "property.safe_transfer_then_buy_order_sensitive."
                "no_negative_cash"
            ],
        ),
    ):
        document = lifecycle_document(control)
        lowered = lower_fsir(
            document,
            f"FsirLifecycle{mode.title()}",
            tla_tools_jar=jar,
        )
        lowered_by_mode[mode] = lowered
        artifact_dir = output / mode
        write_lowered_fsir(lowered, artifact_dir)
        (artifact_dir / "input.fsir.json").write_text(
            canonical_json(
                document.model_dump(by_alias=True, exclude_none=True)
                if hasattr(document, "model_dump")
                else document.dict(by_alias=True, exclude_none=True)
            ),
            encoding="utf-8",
        )
        completed, tlc_output = run_tlc(
            artifact_dir, lowered.module_name, jar
        )
        (artifact_dir / "tlc-output.txt").write_text(
            tlc_output, encoding="utf-8"
        )
        classification = classify_tlc_result(
            completed.returncode,
            tlc_output,
            lowered.source_map,
        )
        trace = (
            normalize_tlc_counterexample(tlc_output, lowered.source_map)
            if classification.kind
            in {"property_violation", "temporal_violation"}
            else []
        )
        (artifact_dir / "normalized-trace.json").write_text(
            canonical_json(trace), encoding="utf-8"
        )
        (artifact_dir / "classification.json").write_text(
            canonical_json(classification.to_json()), encoding="utf-8"
        )
        satisfied = (
            classification.kind == expected
            and list(classification.violated_property_ids)
            == expected_property_ids
            and (
                classification.kind == "passed"
                or bool(trace)
            )
        )
        execution_report = {
            "schema_version": "fsir-tla-execution-report-0.1",
            "module_name": lowered.module_name,
            "expected_classification": expected,
            "expected_property_ids": expected_property_ids,
            "observed_classification": classification.kind,
            "observed_property_ids": list(
                classification.violated_property_ids
            ),
            "normalized_trace_steps": len(trace),
            "satisfied": satisfied,
        }
        (artifact_dir / "execution-report.json").write_text(
            canonical_json(execution_report), encoding="utf-8"
        )
        execution_manifest = build_execution_evidence_manifest(
            lowered=lowered,
            tlc_output=tlc_output,
            normalized_trace=trace,
            classification=classification,
            execution_report=execution_report,
        )
        verify_execution_evidence(
            lowered=lowered,
            tlc_output=tlc_output,
            normalized_trace=trace,
            classification=classification,
            execution_report=execution_report,
            execution_manifest=execution_manifest,
        )
        (artifact_dir / "execution-evidence-manifest.json").write_text(
            canonical_json(execution_manifest), encoding="utf-8"
        )
        execution_records[mode] = {
            "lowered": lowered,
            "tlc_output": tlc_output,
            "normalized_trace": trace,
            "classification": classification,
            "execution_report": execution_report,
            "execution_manifest": execution_manifest,
        }
        all_ok = all_ok and satisfied
        cases[mode] = {
            "control_kind": control,
            "expected": expected,
            "expected_property_ids": expected_property_ids,
            "observed": classification.kind,
            "observed_property_ids": list(
                classification.violated_property_ids
            ),
            "returncode": completed.returncode,
            "manifest": lowered.manifest,
            "execution_evidence_manifest": execution_manifest,
            "normalized_trace_steps": len(trace),
            "normalized_event_ids": [item["event_id"] for item in trace],
            "satisfied": satisfied,
        }

    document = lifecycle_document("sequence")
    lowered = lower_fsir(
        document,
        "FsirLifecycleIntegrity",
        tla_tools_jar=jar,
    )
    mutants = {
        "model": replace(
            lowered,
            tla_text=lowered.tla_text.replace(">= 0", ">= -1", 1),
        ),
        "config": replace(
            lowered,
            cfg_text=lowered.cfg_text.replace("INVARIANTS", "\\* INVARIANTS", 1),
        ),
        "source_map": replace(
            lowered,
            source_map={**lowered.source_map, "operators": {}},
        ),
        "manifest": replace(
            lowered,
            manifest={**lowered.manifest, "outputs": {}},
        ),
    }
    mutation_results = {}
    infrastructure_classification = classify_tlc_result(
        150,
        "Error: Cannot find source file for module MissingConcurrentModule.",
        lowered_by_mode["concurrent"].source_map,
    )
    infrastructure_rejected = (
        infrastructure_classification.kind == "infrastructure_failure"
    )
    mutation_results["infrastructure_not_property_violation"] = {
        "rejected": infrastructure_rejected,
        "classification": infrastructure_classification.to_json(),
    }
    all_ok = all_ok and infrastructure_rejected
    concurrent_record = execution_records["concurrent"]
    try:
        verify_execution_evidence(
            **{
                **concurrent_record,
                "tlc_output": concurrent_record["tlc_output"] + "\nmutated",
            }
        )
    except ValueError as error:
        mutation_results["execution_output_integrity"] = {
            "rejected": True,
            "error": str(error),
        }
    else:
        mutation_results["execution_output_integrity"] = {
            "rejected": False
        }
        all_ok = False
    for name, mutant in mutants.items():
        try:
            verify_lowered_fsir(
                document,
                mutant,
                tla_tools_jar=jar,
            )
        except ValueError as error:
            mutation_results[name] = {
                "rejected": True,
                "error": str(error),
            }
        else:
            mutation_results[name] = {"rejected": False}
            all_ok = False

    raw = (
        document.model_dump(by_alias=True, exclude_none=True)
        if hasattr(document, "model_dump")
        else document.dict(by_alias=True, exclude_none=True)
    )
    property_raw = copy.deepcopy(raw)
    liveness = next(
        prop
        for prop in property_raw["properties"]
        if prop["id"] == "property.lifecycle.buy_fills"
    )
    liveness["formula"]["args"][0]["right"]["value"] = "submitted"
    property_mutant = FsirDocument(**property_raw)
    try:
        verify_lowered_fsir(
            property_mutant,
            lowered,
            tla_tools_jar=jar,
        )
    except ValueError as error:
        mutation_results["property_formula"] = {
            "rejected": True,
            "error": str(error),
        }
    else:
        mutation_results["property_formula"] = {"rejected": False}
        all_ok = False

    bypass_raw = copy.deepcopy(raw)
    submit = next(
        action
        for action in bypass_raw["actions"]
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
    bypass_mutant = FsirDocument(**bypass_raw)
    try:
        lower_fsir(
            bypass_mutant,
            "FsirLifecyclePolicyBypass",
            tla_tools_jar=jar,
        )
    except UnsupportedFsirError as error:
        mutation_results["unmapped_financial_effect"] = {
            "rejected": True,
            "error": str(error),
        }
    else:
        mutation_results["unmapped_financial_effect"] = {
            "rejected": False
        }
        all_ok = False

    report = {
        "schema_version": "fsir-tla-evidence-0.1",
        "verdict": "pass" if all_ok else "fail",
        "cases": cases,
        "integrity_mutations": mutation_results,
    }
    (output / "report.json").write_text(
        canonical_json(report), encoding="utf-8"
    )
    suite_payloads = {
        "report": canonical_json(report),
        **{
            f"{mode}_execution_manifest": canonical_json(
                record["execution_manifest"]
            )
            for mode, record in execution_records.items()
        },
    }
    suite_manifest = {
        "schema_version": "fsir-tla-evidence-suite-0.1",
        "hash_algorithm": "sha256",
        "artifacts": {
            name: hashlib.sha256(payload.encode("utf-8")).hexdigest()
            for name, payload in suite_payloads.items()
        },
    }
    (output / "suite-evidence-manifest.json").write_text(
        canonical_json(suite_manifest), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
