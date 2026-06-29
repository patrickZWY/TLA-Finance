"""Command-line interface for the finance safety gate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from safety.agent import TlaSafetyAgent, TlaSafetyAgentResult
from safety.models import SafetyInputError, SafetyPolicy
from safety.transformer import FinanceActionsBlockTransformer, JsonActionTransformer, OpenAIActionTransformer


def main() -> int:
    parser = argparse.ArgumentParser(description="Check finance-agent actions with TLA+ safety policy.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="check structured finance actions")
    check.add_argument(
        "--actions",
        required=True,
        type=Path,
        help="finance-agent output file; JSON actions by default, prose if --transformer openai",
    )
    check.add_argument("--policy", required=True, type=Path, help="JSON file containing safety policy")
    check.add_argument(
        "--transformer",
        choices=("json", "block", "openai"),
        default="json",
        help="how to transform finance-agent output into structured actions",
    )
    check.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("artifacts/safety-runs"),
        help="directory where generated JSON, TLA, CFG, and reports are stored",
    )
    check.add_argument("--run-name", help="stable run name; defaults to UTC timestamp")
    check.add_argument("--skip-tlc", action="store_true", help="generate TLA artifacts but do not run TLC")
    check.add_argument(
        "--auto-decision",
        choices=("ask", "stop", "continue"),
        default="ask",
        help="decision policy when warnings are found",
    )

    args = parser.parse_args()
    if args.command == "check":
        return _check(args)
    return 1


def _check(args: argparse.Namespace) -> int:
    run_name = args.run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        finance_agent_output = args.actions.read_text(encoding="utf-8")
        policy_raw = json.loads(args.policy.read_text(encoding="utf-8"))
        if not isinstance(policy_raw, dict):
            raise SafetyInputError("policy JSON must be an object")
        policy = SafetyPolicy.from_json(policy_raw)
    except (OSError, json.JSONDecodeError, SafetyInputError) as exc:
        print(f"Input error: {exc}")
        return 3

    if args.transformer == "block":
        transformer = FinanceActionsBlockTransformer()
    elif args.transformer == "openai":
        transformer = OpenAIActionTransformer()
    else:
        transformer = JsonActionTransformer()
    agent = TlaSafetyAgent(artifact_root=args.artifact_dir, transformer=transformer)
    try:
        result = agent.check(
            finance_agent_output,
            policy,
            run_name=run_name,
            run_model_checker=not args.skip_tlc,
            user_decision=None if args.auto_decision == "ask" else args.auto_decision,
        )
    except SafetyInputError as exc:
        print(f"Input error: {exc}")
        return 3

    if result.requires_user_decision:
        decision = _ask_user_decision()
        try:
            result = agent.check(
                finance_agent_output,
                policy,
                run_name=run_name,
                run_model_checker=not args.skip_tlc,
                user_decision=decision,
            )
        except SafetyInputError as exc:
            print(f"Input error: {exc}")
            return 3

    _print_report(result)

    if result.findings and result.decision != "continue":
        return 2
    return 0


def _ask_user_decision() -> str:
    print("\nSafety warning: proposed finance actions did not pass the safety gate.")
    print("Type 'yes' to continue anyway, or anything else to stop.")
    response = input("Continue with these actions? ").strip().lower()
    return "continue" if response == "yes" else "stop"


def _print_report(result: TlaSafetyAgentResult) -> None:
    report = result.to_json()
    print("\nFinance safety check")
    print(f"Decision: {report['decision']}")
    print(f"Safe to execute: {report['safe_to_execute']}")
    print(f"Artifacts: {report['artifacts']['directory']}")  # type: ignore[index]

    findings = report["findings"]
    if findings:
        print("\nFindings:")
        for finding in findings:  # type: ignore[assignment]
            location = f" action {finding['action_index']}:" if "action_index" in finding else ""
            print(f"- {finding['severity']} {finding['code']}{location} {finding['message']}")
    else:
        print("\nNo policy findings.")

    pluscal = report["pluscal"]
    tlc = report["tlc"]
    usage = report["transformer_usage"]
    if usage:
        print(f"\nTransformer token ceiling: {usage['estimated_total_token_ceiling']}")  # type: ignore[index]
    print(f"\nPlusCal status: {pluscal['status']}")  # type: ignore[index]
    print(f"\nTLC status: {tlc['status']}")  # type: ignore[index]


if __name__ == "__main__":
    raise SystemExit(main())
