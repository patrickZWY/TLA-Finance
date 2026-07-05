"""Run semantic extraction evaluation across multiple model backends."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from safety.evaluator import (
    SemanticEvalConfig,
    SemanticEvalThresholds,
    evaluate_thresholds,
    run_semantic_eval,
    write_eval_report,
)


DEFAULT_LOCAL_MODELS = "qwen3:4b,llama3.2:3b,qwen3:1.7b"
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"


@dataclass(frozen=True)
class MatrixBackend:
    name: str
    transformer: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class MatrixConfig:
    cases_path: Path
    repo_root: Path = Path(".")
    output_dir: Path = Path("artifacts/research-eval/model-matrix")
    local_models: tuple[str, ...] = ()
    local_base_url: str = DEFAULT_LOCAL_BASE_URL
    paid_model: str | None = None
    paid_api_key_env: str = "OPENAI_API_KEY"
    include_gold: bool = True
    max_tokens: int = 512
    thresholds: SemanticEvalThresholds = field(default_factory=SemanticEvalThresholds)


def build_backends(config: MatrixConfig) -> list[MatrixBackend]:
    backends: list[MatrixBackend] = []
    if config.include_gold:
        backends.append(MatrixBackend(name="gold", transformer="gold"))

    for model in config.local_models:
        backends.append(
            MatrixBackend(
                name=f"local:{model}",
                transformer="openai",
                model=model,
                base_url=config.local_base_url,
            )
        )

    if config.paid_model:
        api_key = os.getenv(config.paid_api_key_env)
        if api_key:
            backends.append(
                MatrixBackend(
                    name=f"paid:{config.paid_model}",
                    transformer="openai",
                    model=config.paid_model,
                    base_url="",
                    api_key=api_key,
                )
            )
        else:
            backends.append(
                MatrixBackend(
                    name=f"paid:{config.paid_model}",
                    transformer="openai",
                    model=config.paid_model,
                    base_url="",
                    skip_reason=f"{config.paid_api_key_env} is not set",
                )
            )

    return backends


def run_eval_matrix(config: MatrixConfig) -> dict[str, Any]:
    started_at = _now_iso()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    backend_results = [_run_backend(backend, config) for backend in build_backends(config)]
    summary = _matrix_summary(backend_results)
    return {
        "started_at": started_at,
        "completed_at": _now_iso(),
        "config": {
            "cases_path": str(config.cases_path),
            "repo_root": str(config.repo_root),
            "output_dir": str(config.output_dir),
            "local_models": list(config.local_models),
            "local_base_url": config.local_base_url,
            "paid_model": config.paid_model,
            "paid_api_key_env": config.paid_api_key_env,
            "include_gold": config.include_gold,
            "max_tokens": config.max_tokens,
            "thresholds": _threshold_values(config.thresholds),
        },
        "summary": summary,
        "backends": backend_results,
    }


def write_matrix_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run semantic extractor evals across model backends.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/semantic_codex_cases.json"),
        help="labeled semantic eval fixture file",
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="repository root")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research-eval/model-matrix"),
        help="directory for per-model and combined JSON reports",
    )
    parser.add_argument(
        "--local-models",
        default=os.getenv("SEMANTIC_EVAL_MODELS", DEFAULT_LOCAL_MODELS),
        help="comma-separated local model names; empty string skips local models",
    )
    parser.add_argument(
        "--local-base-url",
        default=(
            os.getenv("SEMANTIC_EVAL_LOCAL_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or DEFAULT_LOCAL_BASE_URL
        ),
        help="OpenAI-compatible base URL for local models",
    )
    parser.add_argument(
        "--paid-model",
        default=os.getenv("SEMANTIC_EVAL_PAID_MODEL"),
        help="optional paid API baseline model, for example gpt-4o-mini",
    )
    parser.add_argument(
        "--paid-api-key-env",
        default=os.getenv("SEMANTIC_EVAL_PAID_API_KEY_ENV", "OPENAI_API_KEY"),
        help="environment variable containing the paid API key",
    )
    parser.add_argument("--max-tokens", type=int, default=512, help="extractor output token cap")
    parser.add_argument(
        "--min-pass-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum case pass rate required for backend status=passed",
    )
    parser.add_argument(
        "--min-schema-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum schema-valid extraction rate required for backend status=passed",
    )
    parser.add_argument(
        "--min-exact-action-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum exact canonical-action match rate required for backend status=passed",
    )
    parser.add_argument(
        "--min-finding-code-rate",
        type=_threshold_value,
        default=1.0,
        help="minimum downstream finding-code match rate required for backend status=passed",
    )
    parser.add_argument("--no-gold", action="store_true", help="omit the gold fixture baseline")
    parser.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="return exit code 2 when any non-skipped backend has failed cases or errors",
    )
    args = parser.parse_args(argv)

    config = MatrixConfig(
        cases_path=args.cases,
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        local_models=tuple(_parse_csv(args.local_models)),
        local_base_url=args.local_base_url,
        paid_model=args.paid_model,
        paid_api_key_env=args.paid_api_key_env,
        include_gold=not args.no_gold,
        max_tokens=args.max_tokens,
        thresholds=SemanticEvalThresholds(
            min_pass_rate=args.min_pass_rate,
            min_schema_rate=args.min_schema_rate,
            min_exact_action_rate=args.min_exact_action_rate,
            min_finding_code_rate=args.min_finding_code_rate,
        ),
    )
    report = run_eval_matrix(config)
    output_path = args.output_dir / "model_eval_matrix.json"
    write_matrix_report(report, output_path)
    _print_matrix_summary(report, output_path)
    if args.fail_on_failure and report["summary"]["failed_backends"]:
        return 2
    return 0


def _run_backend(backend: MatrixBackend, config: MatrixConfig) -> dict[str, Any]:
    if backend.skip_reason:
        return {
            "name": backend.name,
            "status": "skipped",
            "skip_reason": backend.skip_reason,
            "model": backend.model,
            "transformer": backend.transformer,
            "report_path": None,
            "summary": None,
        }

    output_path = config.output_dir / f"{_safe_label(backend.name)}.json"
    try:
        report = run_semantic_eval(
            SemanticEvalConfig(
                cases_path=config.cases_path,
                repo_root=config.repo_root,
                transformer=backend.transformer,  # type: ignore[arg-type]
                model=backend.model,
                base_url=backend.base_url,
                api_key=backend.api_key,
                max_tokens=config.max_tokens,
                label=backend.name,
            )
        )
        summary = report["summary"]
        threshold_report = evaluate_thresholds(summary, config.thresholds)
        report["thresholds"] = threshold_report
        write_eval_report(report, output_path)
        status = "passed" if threshold_report["passed"] else "failed"
        return {
            "name": backend.name,
            "status": status,
            "model": backend.model,
            "transformer": backend.transformer,
            "report_path": str(output_path),
            "summary": {
                "total_cases": summary["total_cases"],
                "passed_cases": summary["passed_cases"],
                "failed_cases": summary["failed_cases"],
                "schema_valid_cases": summary["schema_valid_cases"],
                "exact_action_matches": summary["exact_action_matches"],
                "finding_code_matches": summary["finding_code_matches"],
                "latency_ms": summary["latency_ms"],
                "failed_case_names": summary["failed_case_names"],
                "by_category": summary["by_category"],
                "all_cases_passed": summary["all_cases_passed"],
                "threshold_passed": threshold_report["passed"],
                "threshold_rates": threshold_report["rates"],
                "threshold_failures": threshold_report["failures"],
            },
        }
    except Exception as exc:
        return {
            "name": backend.name,
            "status": "error",
            "model": backend.model,
            "transformer": backend.transformer,
            "report_path": None,
            "summary": None,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def _matrix_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    failed = [
        str(result["name"])
        for result in results
        if result["status"] in {"failed", "error"}
    ]
    return {
        "total_backends": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "failed_backends": failed,
        "skipped_backends": [str(result["name"]) for result in results if result["status"] == "skipped"],
    }


def _print_matrix_summary(report: dict[str, Any], output_path: Path) -> None:
    print("Semantic model evaluation matrix")
    for backend in report["backends"]:
        status = backend["status"]
        name = backend["name"]
        if status == "skipped":
            print(f"- {name}: skipped ({backend['skip_reason']})")
            continue
        if status == "error":
            error = backend.get("error") or {}
            print(f"- {name}: error ({error.get('type')}: {error.get('message')})")
            continue
        summary = backend["summary"]
        latency = summary["latency_ms"]
        print(
            f"- {name}: {status}, "
            f"{summary['passed_cases']}/{summary['total_cases']} cases, "
            f"exact={summary['exact_action_matches']}, "
            f"findings={summary['finding_code_matches']}, "
            f"median_ms={latency['median']}"
        )
        if summary.get("threshold_failures"):
            print(f"  threshold failures: {'; '.join(summary['threshold_failures'])}")
    print(f"Combined report: {output_path}")


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _threshold_values(thresholds: SemanticEvalThresholds) -> dict[str, float]:
    return {
        "min_pass_rate": thresholds.min_pass_rate,
        "min_schema_rate": thresholds.min_schema_rate,
        "min_exact_action_rate": thresholds.min_exact_action_rate,
        "min_finding_code_rate": thresholds.min_finding_code_rate,
    }


def _threshold_value(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold must be a number from 0 to 1") from exc
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
