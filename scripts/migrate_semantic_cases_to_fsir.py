"""Deterministically migrate the 12 semantic seed cases to FSIR v0.1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safety.fsir import UnresolvedItem, dump_fsir, legacy_to_fsir  # noqa: E402


DEFAULT_INPUT = ROOT / "fixtures" / "semantic_codex_cases.json"
DEFAULT_OUTPUT = ROOT / "fixtures" / "fsir" / "semantic_codex_cases.fsir.json"


def migrate_cases(cases: list[dict[str, Any]], repo_root: Path = ROOT) -> dict[str, Any]:
    migrated: list[dict[str, Any]] = []
    for case in cases:
        name = str(case["name"])
        source_text = (
            "User request:\n"
            f"{case['user_request']}\n\n"
            "Finance agent response:\n"
            f"{case['finance_agent_response']}"
        )
        policy_path = repo_root / "fixtures" / str(case["policy"])
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        legacy = case["codex_generated_actions"]
        actions = legacy.get("actions")

        unresolved: list[UnresolvedItem] = []
        if case.get("risk_type") == "incomplete_action":
            intent = "underspecified_action"
            unresolved.append(
                UnresolvedItem(
                    id=f"unresolved.{name}.amount",
                    kind="missing_value",
                    severity="blocking",
                    blocks=[],
                    question="What dollar amount should the intended transfer or buy use?",
                    source_span_ids=[f"span.{name}.text"],
                )
            )
        elif isinstance(actions, list) and not actions:
            intent = "no_action"
        else:
            intent = "action_plan"

        document = legacy_to_fsir(
            legacy,
            source_text=source_text,
            case_id=name,
            policy=policy,
            intent=intent,
            unresolved=unresolved,
        )
        migrated.append(
            {
                "name": name,
                "category": case.get("category", "uncategorized"),
                "risk_type": case.get("risk_type", "unspecified"),
                "expected_finding_codes": sorted(
                    str(code) for code in case.get("expected_finding_codes", [])
                ),
                "fsir": dump_fsir(document),
            }
        )

    return {
        "schema_version": "fsir-seed-suite-0.1",
        "source_fixture": "fixtures/semantic_codex_cases.json",
        "case_count": len(migrated),
        "cases": migrated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = json.loads(args.input.read_text(encoding="utf-8"))
    suite = migrate_cases(cases, repo_root=ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(suite, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Migrated {suite['case_count']} cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
