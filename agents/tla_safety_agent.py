"""Callable TLA safety agent wrapper for finance-agent prose output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import has_openai_api_key
from safety.agent import TlaSafetyAgent
from safety.models import SafetyPolicy
from safety.transformer import FinanceActionsBlockTransformer, JsonActionTransformer, OpenAIActionTransformer


def run(
    finance_agent_output: str,
    policy: SafetyPolicy | dict[str, Any],
    *,
    run_name: str | None = None,
    artifact_root: Path | str = Path("artifacts/safety-runs"),
    run_model_checker: bool = True,
    user_decision: str | None = None,
    structured_json: bool = False,
) -> dict[str, Any]:
    """Run the TLA safety agent.

    By default this wrapper expects prose from the current finance agent and
    semantically extracts canonical actions with the LLM transformer. Set
    `structured_json=True` for pre-normalized fixture JSON.
    """

    if structured_json:
        transformer = JsonActionTransformer()
    elif has_openai_api_key():
        transformer = OpenAIActionTransformer()
    else:
        transformer = FinanceActionsBlockTransformer()
    agent = TlaSafetyAgent(artifact_root=artifact_root, transformer=transformer)
    return agent.check(
        finance_agent_output,
        policy,
        run_name=run_name,
        run_model_checker=run_model_checker,
        user_decision=user_decision,  # type: ignore[arg-type]
    ).to_json()


__all__ = ["TlaSafetyAgent", "run"]
