"""Semantic extractor evaluation helpers."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from safety.models import FinanceAction, SafetyInputError, SafetyPolicy, dump_actions, load_actions
from safety.transformer import OpenAIActionTransformer
from safety.validator import evaluate_policy


TransformerKind = Literal["gold", "openai"]


@dataclass(frozen=True)
class SemanticEvalConfig:
    cases_path: Path
    repo_root: Path = Path(".")
    transformer: TransformerKind = "gold"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int = 512
    label: str | None = None


@dataclass(frozen=True)
class SemanticEvalThresholds:
    min_pass_rate: float = 1.0
    min_schema_rate: float = 1.0
    min_exact_action_rate: float = 1.0
    min_finding_code_rate: float = 1.0


class GoldActionTransformer:
    """Offline stand-in that returns the labeled canonical actions."""

    def __init__(self, generated_actions: dict[str, Any]) -> None:
        self.actions = load_actions(generated_actions, allow_empty=True)
        self.last_usage_estimate = {
            "model": "gold-fixture",
            "estimated_total_token_ceiling": 0,
        }
        self.last_raw_content = json.dumps(generated_actions, separators=(",", ":"))

    def transform(self, finance_agent_output: str) -> list[FinanceAction]:
        if "```finance-actions" in finance_agent_output:
            raise SafetyInputError("semantic eval cases must use natural prose, not fenced action blocks")
        return self.actions


def run_semantic_eval(config: SemanticEvalConfig) -> dict[str, Any]:
    """Run extractor evaluation over labeled semantic cases."""

    started_at = _now_iso()
    cases = _load_cases(config.cases_path)
    with _configured_transformer_env(config):
        results = [_evaluate_case(case, config) for case in cases]
    summary = _summarize(results)
    return {
        "started_at": started_at,
        "completed_at": _now_iso(),
        "config": {
            "cases_path": str(config.cases_path),
            "transformer": config.transformer,
            "model": config.model,
            "base_url": config.base_url,
            "max_tokens": config.max_tokens,
            "label": config.label or _default_label(config),
        },
        "summary": summary,
        "cases": results,
    }


def write_eval_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate semantic finance action extraction.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/semantic_codex_cases.json"),
        help="labeled semantic eval fixture file",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="repository root used to resolve policy fixture paths",
    )
    parser.add_argument(
        "--transformer",
        choices=("gold", "openai"),
        default="gold",
        help="gold uses labeled actions; openai calls the configured model backend",
    )
    parser.add_argument("--model", help="model override for the OpenAI-compatible transformer")
    parser.add_argument("--base-url", help="OPENAI_BASE_URL override for this run")
    parser.add_argument("--api-key", help="OPENAI_API_KEY override for this run")
    parser.add_argument("--max-tokens", type=int, default=512, help="extractor output token cap")
    parser.add_argument("--label", help="human-readable run label")
    parser.add_argument(
        "--min-pass-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum case pass rate required for exit code 0",
    )
    parser.add_argument(
        "--min-schema-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum schema-valid extraction rate required for exit code 0",
    )
    parser.add_argument(
        "--min-exact-action-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum exact canonical-action match rate required for exit code 0",
    )
    parser.add_argument(
        "--min-finding-code-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum downstream finding-code match rate required for exit code 0",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write JSON results; defaults under artifacts/research-eval",
    )
    args = parser.parse_args(argv)

    output_path = args.output or _default_output_path(args.transformer, args.model)
    report = run_semantic_eval(
        SemanticEvalConfig(
            cases_path=args.cases,
            repo_root=args.repo_root,
            transformer=args.transformer,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            max_tokens=args.max_tokens,
            label=args.label,
        )
    )
    report["thresholds"] = evaluate_thresholds(
        report["summary"],
        SemanticEvalThresholds(
            min_pass_rate=args.min_pass_rate,
            min_schema_rate=args.min_schema_rate,
            min_exact_action_rate=args.min_exact_action_rate,
            min_finding_code_rate=args.min_finding_code_rate,
        ),
    )
    write_eval_report(report, output_path)
    _print_summary(report, output_path)
    return 0 if report["thresholds"]["passed"] else 2


def _evaluate_case(case: dict[str, Any], config: SemanticEvalConfig) -> dict[str, Any]:
    case_name = str(case["name"])
    natural_agent_output = _natural_agent_output(case)
    expected_actions = case["codex_generated_actions"]
    expected_codes = sorted(set(str(code) for code in case.get("expected_finding_codes", [])))
    transformer = _make_transformer(config.transformer, case, config)

    started = time.perf_counter()
    try:
        actions = transformer.transform(natural_agent_output)
        extraction_latency_ms = _elapsed_ms(started)
        actual_actions = dump_actions(actions)
        policy = _load_policy(config.repo_root, str(case["policy"]))
        actual_codes = sorted({finding.code for finding in evaluate_policy(actions, policy)})
        error = None
        schema_valid = True
    except Exception as exc:
        extraction_latency_ms = _elapsed_ms(started)
        actual_actions = {"actions": []}
        actual_codes = []
        error = {"type": type(exc).__name__, "message": str(exc)}
        schema_valid = False

    exact_action_match = actual_actions == expected_actions
    finding_code_match = actual_codes == expected_codes
    return {
        "name": case_name,
        "category": str(case.get("category", "uncategorized")),
        "risk_type": str(case.get("risk_type", "unspecified")),
        "expected_behavior": str(case.get("expected_behavior", "")),
        "policy": case["policy"],
        "schema_valid": schema_valid,
        "exact_action_match": exact_action_match,
        "finding_code_match": finding_code_match,
        "passed": schema_valid and exact_action_match and finding_code_match,
        "extraction_latency_ms": extraction_latency_ms,
        "expected_actions": expected_actions,
        "actual_actions": actual_actions,
        "expected_finding_codes": expected_codes,
        "actual_finding_codes": actual_codes,
        "error": error,
        "raw_model_output": getattr(transformer, "last_raw_content", ""),
        "transformer_usage": getattr(transformer, "last_usage_estimate", {}),
    }


def _make_transformer(kind: TransformerKind, case: dict[str, Any], config: SemanticEvalConfig):
    if kind == "gold":
        return GoldActionTransformer(case["codex_generated_actions"])
    if kind == "openai":
        return OpenAIActionTransformer(model=config.model, max_tokens=config.max_tokens)
    raise ValueError(f"Unsupported transformer: {kind}")


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(result["extraction_latency_ms"]) for result in results]
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "all_cases_passed": passed == total,
        "schema_valid_cases": sum(1 for result in results if result["schema_valid"]),
        "exact_action_matches": sum(1 for result in results if result["exact_action_match"]),
        "finding_code_matches": sum(1 for result in results if result["finding_code_match"]),
        "latency_ms": _latency_summary(latencies),
        "by_category": _group_summary(results, "category"),
        "by_risk_type": _group_summary(results, "risk_type"),
        "failed_case_names": [result["name"] for result in results if not result["passed"]],
    }


def evaluate_thresholds(
    summary: dict[str, Any],
    thresholds: SemanticEvalThresholds,
) -> dict[str, Any]:
    total = int(summary["total_cases"])
    rates = {
        "pass_rate": _rate(int(summary["passed_cases"]), total),
        "schema_rate": _rate(int(summary["schema_valid_cases"]), total),
        "exact_action_rate": _rate(int(summary["exact_action_matches"]), total),
        "finding_code_rate": _rate(int(summary["finding_code_matches"]), total),
    }
    threshold_values = {
        "min_pass_rate": thresholds.min_pass_rate,
        "min_schema_rate": thresholds.min_schema_rate,
        "min_exact_action_rate": thresholds.min_exact_action_rate,
        "min_finding_code_rate": thresholds.min_finding_code_rate,
    }
    checks = [
        ("pass rate", "pass_rate", thresholds.min_pass_rate),
        ("schema rate", "schema_rate", thresholds.min_schema_rate),
        ("exact action rate", "exact_action_rate", thresholds.min_exact_action_rate),
        ("finding-code rate", "finding_code_rate", thresholds.min_finding_code_rate),
    ]
    failures = [
        f"{label} {rates[rate_key]:.3f} below threshold {minimum:.3f}"
        for label, rate_key, minimum in checks
        if rates[rate_key] < minimum
    ]
    return {
        "passed": not failures,
        "rates": rates,
        "thresholds": threshold_values,
        "failures": failures,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _latency_summary(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "median": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "min": ordered[0],
        "median": int(statistics.median(ordered)),
        "p95": ordered[p95_index],
        "max": ordered[-1],
        "mean": round(statistics.fmean(ordered), 2),
    }


def _group_summary(results: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for result in results:
        key = str(result.get(field) or "unspecified")
        bucket = grouped.setdefault(
            key,
            {
                "total_cases": 0,
                "passed_cases": 0,
                "schema_valid_cases": 0,
                "exact_action_matches": 0,
                "finding_code_matches": 0,
            },
        )
        bucket["total_cases"] += 1
        bucket["passed_cases"] += int(bool(result["passed"]))
        bucket["schema_valid_cases"] += int(bool(result["schema_valid"]))
        bucket["exact_action_matches"] += int(bool(result["exact_action_match"]))
        bucket["finding_code_matches"] += int(bool(result["finding_code_match"]))
    return dict(sorted(grouped.items()))


def _load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("semantic eval fixture must contain a JSON list")
    return raw


def _load_policy(repo_root: Path, policy_name: str) -> SafetyPolicy:
    path = repo_root / "fixtures" / policy_name
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SafetyInputError("policy fixture must contain a JSON object")
    return SafetyPolicy.from_json(raw)


def _natural_agent_output(case: dict[str, Any]) -> str:
    return (
        "User request:\n"
        f"{case['user_request']}\n\n"
        "Finance agent response:\n"
        f"{case['finance_agent_response']}"
    )


def _default_output_path(transformer: str, model: str | None) -> Path:
    label = model or transformer
    safe_label = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("artifacts/research-eval") / f"semantic_eval_{safe_label}_{stamp}.json"


def _default_label(config: SemanticEvalConfig) -> str:
    if config.model:
        return config.model
    return config.transformer


def _print_summary(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]
    config = report["config"]
    print("Semantic extractor evaluation")
    print(f"Transformer: {config['transformer']}")
    if config.get("model"):
        print(f"Model: {config['model']}")
    print(f"Cases: {summary['passed_cases']}/{summary['total_cases']} passed")
    print(f"Schema valid: {summary['schema_valid_cases']}/{summary['total_cases']}")
    print(f"Exact actions: {summary['exact_action_matches']}/{summary['total_cases']}")
    print(f"Finding codes: {summary['finding_code_matches']}/{summary['total_cases']}")
    categories = [
        f"{name} {bucket['passed_cases']}/{bucket['total_cases']}"
        for name, bucket in summary["by_category"].items()
    ]
    if categories:
        print(f"Categories: {', '.join(categories)}")
    print(f"Latency ms: {summary['latency_ms']}")
    if summary["failed_case_names"]:
        print(f"Failed cases: {', '.join(summary['failed_case_names'])}")
    if report.get("thresholds"):
        thresholds = report["thresholds"]
        status = "passed" if thresholds["passed"] else "failed"
        print(f"Thresholds: {status}")
        for failure in thresholds["failures"]:
            print(f"- {failure}")
    print(f"Report: {output_path}")


def _threshold_value(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold must be a number from 0 to 1") from exc
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return parsed


def _elapsed_ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _configured_transformer_env(config: SemanticEvalConfig):
    keys = ("OPENAI_BASE_URL", "LOCAL_LLM_BASE_URL", "OPENAI_API_KEY")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        if config.base_url is not None:
            os.environ["OPENAI_BASE_URL"] = config.base_url
            os.environ["LOCAL_LLM_BASE_URL"] = ""
        if config.api_key is not None:
            os.environ["OPENAI_API_KEY"] = config.api_key
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
