"""Agent boundary for TLA-backed finance action safety checks."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import observability
from safety.checker import run_tlc, translate_pluscal
from safety.models import SafetyInputError, SafetyPolicy, dump_actions
from safety.tla_generator import generate_tla, write_tla_artifacts
from safety.transformer import ActionTransformer, JsonActionTransformer
from safety.validator import SafetyFinding, evaluate_policy


UserDecision = Literal["stop", "continue"]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TlaSafetyAgentResult:
    """Structured result returned by the TLA safety agent."""

    safe_to_execute: bool
    decision: str
    findings: list[SafetyFinding]
    artifact_dir: Path
    tla_path: Path
    cfg_path: Path
    pluscal: dict[str, object]
    tlc: dict[str, object]
    transformer_usage: dict[str, object]
    observability: dict[str, object]

    @property
    def requires_user_decision(self) -> bool:
        return self.decision == "requires_user_decision"

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": "tla_safety_agent",
            "safe_to_execute": self.safe_to_execute,
            "decision": self.decision,
            "requires_user_decision": self.requires_user_decision,
            "findings": [finding.to_json() for finding in self.findings],
            "artifacts": {
                "directory": str(self.artifact_dir),
                "tla": str(self.tla_path),
                "cfg": str(self.cfg_path),
            },
            "pluscal": self.pluscal,
            "tlc": self.tlc,
            "transformer_usage": self.transformer_usage,
            "observability": self.observability,
        }


class TlaSafetyAgent:
    """Checks untrusted finance-agent actions before execution.

    The agent performs the complete v1 pipeline:
    transform finance-agent output to action JSON, evaluate the policy mirror,
    generate PlusCal/TLA+ artifacts, translate PlusCal, run TLC, and produce a
    decision report for the caller/API.
    """

    def __init__(
        self,
        artifact_root: Path | str = Path("artifacts/safety-runs"),
        transformer: ActionTransformer | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.transformer = transformer or JsonActionTransformer()

    def check(
        self,
        finance_agent_output: str,
        policy: SafetyPolicy | dict[str, Any],
        *,
        run_name: str | None = None,
        run_model_checker: bool = True,
        user_decision: UserDecision | None = None,
        run_id: str | None = None,
    ) -> TlaSafetyAgentResult:
        total_start = time.perf_counter()
        started_at = observability.now_iso()
        stage_durations_ms: dict[str, int] = {}
        run_id = run_id or str(observability.current_context().get("safety_run_id") or observability.new_id("safety"))
        run_name = run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = self.artifact_root / run_name
        artifact_dir.mkdir(parents=True, exist_ok=True)

        transformer_name = type(self.transformer).__name__
        observability.log_event(
            logger,
            "safety.pipeline.start",
            safety_run_id=run_id,
            transformer_name=transformer_name,
            model_checker_enabled=run_model_checker,
            artifact_dir=str(artifact_dir),
        )

        with observability.scoped_context(safety_run_id=run_id):
            with observability.timed_stage(stage_durations_ms, "coerce_policy"):
                resolved_policy = _coerce_policy(policy)
            with observability.timed_stage(
                stage_durations_ms,
                "transform",
                logger,
                "safety.pipeline.stage",
                transformer_name=transformer_name,
            ):
                actions = self.transformer.transform(finance_agent_output)
        transformer_usage = getattr(self.transformer, "last_usage_estimate", {})
        with observability.timed_stage(
            stage_durations_ms,
            "evaluate_policy",
            logger,
            "safety.pipeline.stage",
            safety_run_id=run_id,
            action_count=len(actions),
        ):
            findings = evaluate_policy(actions, resolved_policy)

        module_name = f"FinanceSafety_{run_name}"
        with observability.timed_stage(stage_durations_ms, "generate_tla"):
            generated = generate_tla(actions, resolved_policy, module_name)
        with observability.timed_stage(stage_durations_ms, "write_artifacts"):
            tla_path, cfg_path = write_tla_artifacts(generated, artifact_dir)

        with observability.timed_stage(stage_durations_ms, "write_report_inputs"):
            (artifact_dir / "finance_agent_output.txt").write_text(
                finance_agent_output,
                encoding="utf-8",
            )
            (artifact_dir / "normalized_actions.json").write_text(
                json.dumps(dump_actions(actions), indent=2) + "\n",
                encoding="utf-8",
            )
            (artifact_dir / "policy.json").write_text(
                json.dumps(resolved_policy.to_json(), indent=2) + "\n",
                encoding="utf-8",
            )

        if run_model_checker:
            with observability.scoped_context(safety_run_id=run_id):
                with observability.timed_stage(stage_durations_ms, "formal_checks"):
                    pluscal, tlc = self._run_formal_checks(tla_path, cfg_path, artifact_dir, findings)
        else:
            stage_durations_ms["formal_checks"] = 0
            pluscal = {
                "status": "skipped",
                "command": [],
                "returncode": None,
                "output": "PlusCal translation skipped.",
            }
            tlc = {
                "status": "skipped",
                "command": [],
                "returncode": None,
                "output": "TLC run skipped.",
            }

        decision = _resolve_decision(findings, user_decision)
        observability_info: dict[str, object] = {
            "run_id": run_id,
            "started_at": started_at,
            "duration_ms": observability.elapsed_ms(total_start),
            "stage_durations_ms": stage_durations_ms,
            "transformer_name": transformer_name,
            "action_count": len(actions),
            "finding_codes": [finding.code for finding in findings],
            "model_checker_enabled": run_model_checker,
        }
        result = TlaSafetyAgentResult(
            safe_to_execute=not findings or decision == "continue",
            decision=decision,
            findings=findings,
            artifact_dir=artifact_dir,
            tla_path=tla_path,
            cfg_path=cfg_path,
            pluscal=pluscal,
            tlc=tlc,
            transformer_usage=transformer_usage,
            observability=observability_info,
        )
        (artifact_dir / "report.json").write_text(
            json.dumps(result.to_json(), indent=2) + "\n",
            encoding="utf-8",
        )
        observability.log_event(
            logger,
            "safety.pipeline.end",
            safety_run_id=run_id,
            status="safe" if result.safe_to_execute else "blocked",
            decision=result.decision,
            duration_ms=observability_info["duration_ms"],
            action_count=len(actions),
            finding_count=len(findings),
            finding_codes=observability_info["finding_codes"],
            pluscal_status=pluscal.get("status"),
            tlc_status=tlc.get("status"),
            artifact_dir=str(artifact_dir),
        )
        return result

    def _run_formal_checks(
        self,
        tla_path: Path,
        cfg_path: Path,
        artifact_dir: Path,
        findings: list[SafetyFinding],
    ) -> tuple[dict[str, object], dict[str, object]]:
        pcal = translate_pluscal(tla_path)
        pluscal = pcal.to_json()
        (artifact_dir / "pcal_output.txt").write_text(pcal.output, encoding="utf-8")
        if not pcal.translated:
            findings.append(
                SafetyFinding(
                    code=f"pluscal_{pcal.status}",
                    severity="error" if pcal.status != "not_configured" else "warning",
                    message=pcal.output,
                )
            )
            return pluscal, {
                "status": "skipped",
                "command": [],
                "returncode": None,
                "output": "TLC skipped because PlusCal translation did not complete.",
            }

        result = run_tlc(tla_path, cfg_path)
        tlc = result.to_json()
        (artifact_dir / "tlc_output.txt").write_text(result.output, encoding="utf-8")
        if result.status == "not_configured":
            findings.append(
                SafetyFinding(
                    code="tla_not_configured",
                    severity="warning",
                    message=result.output,
                )
            )
        elif result.status in {"failed", "timeout"}:
            findings.append(
                SafetyFinding(
                    code=f"tlc_{result.status}",
                    severity="error",
                    message=summarize_tlc_failure(result.output),
                )
            )
        return pluscal, tlc


def run(
    finance_agent_output: str,
    policy: SafetyPolicy | dict[str, Any],
    *,
    run_name: str | None = None,
    artifact_root: Path | str = Path("artifacts/safety-runs"),
    run_model_checker: bool = True,
    user_decision: UserDecision | None = None,
) -> dict[str, Any]:
    """Convenience entry point for API/tool callers."""

    agent = TlaSafetyAgent(artifact_root=artifact_root)
    return agent.check(
        finance_agent_output,
        policy,
        run_name=run_name,
        run_model_checker=run_model_checker,
        user_decision=user_decision,
    ).to_json()


def summarize_tlc_failure(output: str) -> str:
    for line in output.splitlines():
        text = line.strip()
        if "Invariant" in text or "invariant" in text:
            return f"TLC did not verify the generated safety model: {text}"
    return "TLC did not verify the generated safety model. See tlc_output.txt."


def _coerce_policy(policy: SafetyPolicy | dict[str, Any]) -> SafetyPolicy:
    if isinstance(policy, SafetyPolicy):
        return policy
    if isinstance(policy, dict):
        return SafetyPolicy.from_json(policy)
    raise SafetyInputError("policy must be a SafetyPolicy or JSON object")


def _resolve_decision(findings: list[SafetyFinding], user_decision: UserDecision | None) -> str:
    if not findings:
        return "safe"
    if user_decision in {"stop", "continue"}:
        return user_decision
    return "requires_user_decision"
