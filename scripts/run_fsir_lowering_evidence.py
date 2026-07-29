#!/usr/bin/env python3
"""Generate reproducible FSIR lowering/TLC evidence for independent review."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from safety.fsir import FsirDocument
from safety.fsir_lowering import (
    UnsupportedFsirError,
    lower_fsir,
    normalize_tlc_counterexample,
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
    all_ok = True
    for mode, control, expected in (
        ("ordered", "sequence", "passed"),
        ("concurrent", "partial_order", "failed"),
    ):
        document = lifecycle_document(control)
        lowered = lower_fsir(
            document,
            f"FsirLifecycle{mode.title()}",
            tla_tools_jar=jar,
        )
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
        trace = normalize_tlc_counterexample(tlc_output, lowered.source_map)
        (artifact_dir / "normalized-trace.json").write_text(
            canonical_json(trace), encoding="utf-8"
        )
        observed = (
            "passed"
            if completed.returncode == 0
            and "No error has been found" in tlc_output
            else "failed"
        )
        all_ok = all_ok and observed == expected
        cases[mode] = {
            "control_kind": control,
            "expected": expected,
            "observed": observed,
            "returncode": completed.returncode,
            "manifest": lowered.manifest,
            "normalized_trace_steps": len(trace),
            "normalized_event_ids": [item["event_id"] for item in trace],
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
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
