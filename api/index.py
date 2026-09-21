from collections import defaultdict, deque
import json
import logging
import os
import random
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# Make the agents package importable for local runs.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
# Also try the directory containing this file.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

from agents import budget_agent, debt_agent, goal_agent, investment_agent, storage
from config import (
    allowed_origins,
    has_openai_api_key,
    normalize_openai_api_key,
    openai_chat_options,
    openai_client,
    openai_model,
    trusted_hosts,
)
import observability
from safety.agent import TlaSafetyAgentResult, summarize_tlc_failure
from safety.artifacts import cleanup_old_safety_artifacts
from safety.checker import (
    parse_tlc_counterexample_history,
    parse_tlc_statistics,
    run_tlc,
    translate_pluscal,
)
from safety.models import FinanceAction, SafetyInputError, SafetyPolicy, dump_actions, load_actions
from safety.tla_generator import generate_branching_tla, write_tla_artifacts
from safety.transformer import (
    ExplicitRequestActionTransformer,
    FinanceActionsBlockTransformer,
    OpenAIActionTransformer,
)
from safety.agent import TlaSafetyAgent
from safety.bounded_workbench import (
    BoundedEvidenceUnavailable,
    canonical_fsir_response,
    corpus_case_response,
)
from safety.validator import SafetyFinding, evaluate_policy

normalize_openai_api_key()
observability.configure_logging()

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMITS: Dict[str, tuple[int, int]] = {
    "/api/bounded-workbench": (20, 60),
    "/api/semantic-check": (10, 60),
    "/api/chat": (5, 60),
    "/api/demo/bad-suggestion": (20, 60),
}

DEFAULT_REQUEST_LIMITS = {
    "user_message_chars": 4_000,
    "finance_advice_chars": 12_000,
    "actions_json_bytes": 128_000,
    "history_items": 40,
    "history_json_bytes": 32_000,
    "policy_json_bytes": 32_000,
    "fsir_json_bytes": 256_000,
    "session_json_bytes": 64_000,
}


class InMemoryRateLimiter:
    def __init__(self, limits: Dict[str, tuple[int, int]]) -> None:
        self.limits = limits
        self._hits: Dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def retry_after(self, path: str, client_id: str, now: float | None = None) -> float | None:
        limit = self.limits.get(path)
        if limit is None:
            return None

        max_requests, window_seconds = limit
        now = time.monotonic() if now is None else now
        hits = self._hits[(path, client_id)]
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= max_requests:
            return max(1.0, window_seconds - (now - hits[0]))

        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()


class RateLimitMiddleware:
    def __init__(self, app, limiter: InMemoryRateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") != "OPTIONS":
            path = scope.get("path", "")
            headers = _headers_from_scope(scope)
            client_id = _client_id_from_scope(scope, headers)
            retry_after = self.limiter.retry_after(path, client_id)
            if retry_after is not None:
                response = JSONResponse(
                    {"detail": "Rate limit exceeded. Try again shortly."},
                    status_code=429,
                    headers={"Retry-After": str(ceil(retry_after))},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _headers_from_scope(scope) -> Dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _client_id_from_scope(scope, headers: Dict[str, str]) -> str:
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        value = headers.get(header)
        if value:
            return value.split(",", 1)[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def request_limits() -> Dict[str, int]:
    return {
        key: _positive_int_env(f"API_MAX_{key.upper()}", default)
        for key, default in DEFAULT_REQUEST_LIMITS.items()
    }


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _validate_chat_request(req: "ChatRequest") -> None:
    limits = request_limits()
    _validate_text_size("message", req.message, limits["user_message_chars"])
    _validate_history(req.history, limits)
    if req.session_data is not None:
        _validate_json_size("session_data", req.session_data, limits["session_json_bytes"])
        policy = req.session_data.get("safety_policy")
        if isinstance(policy, dict):
            _validate_json_size("session_data.safety_policy", policy, limits["policy_json_bytes"])


def _validate_demo_request(req: "SafetyDemoRequest") -> None:
    limits = request_limits()
    _validate_history(req.history, limits)
    if req.session_data is not None:
        _validate_json_size("session_data", req.session_data, limits["session_json_bytes"])
        policy = req.session_data.get("safety_policy")
        if isinstance(policy, dict):
            _validate_json_size("session_data.safety_policy", policy, limits["policy_json_bytes"])


def _validate_semantic_check_request(req: "SemanticCheckRequest") -> None:
    limits = request_limits()
    _validate_text_size("user_message", req.user_message, limits["user_message_chars"])
    _validate_text_size("finance_advice", req.finance_advice, limits["finance_advice_chars"])
    _validate_json_size("policy", req.policy, limits["policy_json_bytes"])
    if req.normalized_actions is not None:
        _validate_json_size("normalized_actions", req.normalized_actions, limits["actions_json_bytes"])


def _validate_text_size(field: str, value: str, max_chars: int) -> None:
    if len(value or "") > max_chars:
        raise HTTPException(
            status_code=413,
            detail=f"{field} exceeds the configured limit of {max_chars} characters.",
        )


def _validate_history(history: List[Dict[str, str]], limits: Dict[str, int]) -> None:
    if len(history) > limits["history_items"]:
        raise HTTPException(
            status_code=413,
            detail=f"history exceeds the configured limit of {limits['history_items']} items.",
        )
    _validate_json_size("history", history, limits["history_json_bytes"])


def _validate_json_size(field: str, value: Any, max_bytes: int) -> None:
    size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{field} exceeds the configured limit of {max_bytes} bytes.",
        )


rate_limiter = InMemoryRateLimiter(DEFAULT_RATE_LIMITS)

app = FastAPI(title="Personal Finance Agent")

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=trusted_hosts(),
)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def cleanup_safety_artifacts_on_startup() -> None:
    removed = cleanup_old_safety_artifacts(_safety_artifact_root())
    if removed:
        observability.log_event(
            logger,
            "api.safety_artifacts.cleanup",
            removed_count=len(removed),
        )

ROUTER_SYSTEM = """You are a finance request router. Analyze the user's message and output ONLY valid JSON.

Available agents: "budget", "goal", "investment", "debt"

- budget: add/view income or expenses, set spending limits, spending analysis
- goal: savings goals, progress tracking, savings plans, deadlines
- investment: risk profiles, portfolio recommendations, compound growth, ETFs, Roth IRA, 401k
- debt: track debts, payoff plans, snowball/avalanche strategy, interest calculations

Output format (JSON only, no other text):
{"agents": ["budget"], "task": "rephrase the request for the agent(s) with all key numbers and context"}

Include all relevant agents. Multiple agents allowed."""

ORCHESTRATOR_SYSTEM = """You are a personal finance orchestrator. You synthesize responses from multiple
specialist agents into one clear, helpful answer. Be warm, encouraging, and specific with numbers.
Use markdown formatting for clarity.

The safety gate reads your response semantically before any concrete money action is allowed. If you
include a fenced action block, it must use this exact shape:
```finance-actions
{"actions":[]}
```

Include only concrete executable money movement, trade, deposit, withdrawal, transfer, buy, sell, or
swap actions. For educational or hypothetical recommendations, use an empty actions list."""

AGENT_MAP: Dict[str, Any] = {
    "budget": (budget_agent.run, "Budget"),
    "goal": (goal_agent.run, "Goal"),
    "investment": (investment_agent.run, "Investment"),
    "debt": (debt_agent.run, "Debt"),
}

CONTINUE_WORDS = {"continue", "proceed", "approve", "approved", "yes", "y", "false positive"}
STOP_WORDS = {"stop", "cancel", "deny", "no", "n", "terminate", "abort"}

FIXTURE_DIR = Path(_root) / "fixtures"
BAD_SAFETY_DEMOS: Dict[str, Dict[str, str]] = {
    "combined_budget_and_item": {
        "title": "Combined budget and individual action limit violation",
        "finance_reply": "finance_reply.complex_bad.combined_budget_and_item.md",
        "policy": "policy.complex_budget700_item400.json",
    },
    "bad_destination_and_budget": {
        "title": "Unauthorized destination and budget violation",
        "finance_reply": "finance_reply.complex_bad.destination_and_budget.md",
        "policy": "policy.complex_budget700_item400.json",
    },
    "buy_before_transfer": {
        "title": "Insufficient balance caused by unsafe action order",
        "finance_reply": "finance_reply.flow_bad.buy_before_transfer.md",
        "policy": "policy.flow_budget600_item300.json",
    },
    "individual_item_limit": {
        "title": "Single action exceeds max individual amount",
        "finance_reply": "finance_reply.complex_bad.individual_item.md",
        "policy": "policy.complex_budget700_item400.json",
    },
}


class ChatRequest(BaseModel):
    message: str
    session_data: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    session_data: Dict[str, Any]
    history: List[Dict[str, str]]


class SafetyDemoRequest(BaseModel):
    session_data: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = Field(default_factory=list)
    example: Optional[str] = None


class SemanticCheckRequest(BaseModel):
    user_message: str = ""
    finance_advice: str
    normalized_actions: Optional[Dict[str, Any]] = None
    benchmark: Optional[str] = None
    policy: Dict[str, Any]
    run_policy_checker: bool = True
    run_model_checker: Optional[bool] = None


class BoundedWorkbenchRequest(BaseModel):
    source: Literal["corpus_case", "canonical_fsir"]
    case_id: Optional[str] = None
    hero_stage: Optional[int] = Field(default=None, ge=1, le=8)
    fsir: Optional[Dict[str, Any]] = None
    run_model_checker: bool = False

    class Config:
        extra = "forbid"


@app.post("/api/chat")
def chat(req: ChatRequest):
    request_id = observability.new_id("req")
    start = time.perf_counter()
    with observability.scoped_context(request_id=request_id):
        try:
            _validate_chat_request(req)
            observability.log_event(
                logger,
                "api.chat.start",
                history_len=len(req.history),
                has_session_data=req.session_data is not None,
                message=observability.payload(req.message),
            )
            response = _chat(req)
        except HTTPException as exc:
            observability.log_event(
                logger,
                "api.chat.end",
                level=logging.ERROR,
                status="http_error",
                status_code=exc.status_code,
                duration_ms=observability.elapsed_ms(start),
            )
            raise
        except Exception as exc:
            observability.log_event(
                logger,
                "api.chat.end",
                level=logging.ERROR,
                status="error",
                error_type=type(exc).__name__,
                duration_ms=observability.elapsed_ms(start),
            )
            raise HTTPException(status_code=500, detail=f"Chat request failed: {exc}") from exc
        observability.log_event(
            logger,
            "api.chat.end",
            status="ok",
            duration_ms=observability.elapsed_ms(start),
            history_len=len(response.history),
        )
        return response


@app.post("/api/semantic-check")
def semantic_check(req: SemanticCheckRequest):
    request_id = observability.new_id("req")
    start = time.perf_counter()
    with observability.scoped_context(request_id=request_id):
        try:
            _validate_semantic_check_request(req)
            return _semantic_check(req)
        except HTTPException:
            raise
        except SafetyInputError as exc:
            observability.log_event(
                logger,
                "api.semantic_check.end",
                level=logging.WARNING,
                status="input_error",
                error_type=type(exc).__name__,
                duration_ms=observability.elapsed_ms(start),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            observability.log_event(
                logger,
                "api.semantic_check.end",
                level=logging.ERROR,
                status="error",
                error_type=type(exc).__name__,
                duration_ms=observability.elapsed_ms(start),
            )
            raise HTTPException(status_code=500, detail=f"Semantic check failed: {exc}") from exc


@app.post("/api/bounded-workbench")
def bounded_workbench(req: BoundedWorkbenchRequest):
    """Run the closed FSIR path without widening legacy prose extraction."""

    if req.source == "corpus_case":
        if not req.case_id or req.fsir is not None:
            raise HTTPException(
                status_code=422,
                detail="corpus_case requires case_id and forbids fsir",
            )
        try:
            return corpus_case_response(req.case_id, req.hero_stage)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="unknown frozen corpus case",
            ) from exc
        except BoundedEvidenceUnavailable as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "bounded_evidence_unavailable",
                    "message": (
                        "Frozen case evidence failed integrity validation."
                    ),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.fsir is None or req.case_id is not None or req.hero_stage is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "canonical_fsir requires fsir and forbids case_id/hero_stage"
            ),
        )
    _validate_json_size(
        "fsir",
        req.fsir,
        request_limits()["fsir_json_bytes"],
    )
    try:
        return canonical_fsir_response(
            req.fsir,
            run_model_checker=req.run_model_checker,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_fsir",
                "message": "FSIR validation failed; no lowering was attempted.",
                "errors": [
                    {
                        "loc": list(item["loc"]),
                        "type": item["type"],
                        "msg": item["msg"],
                    }
                    for item in exc.errors(include_url=False)
                ],
            },
        ) from exc


@app.post("/api/demo/bad-suggestion")
def demo_bad_suggestion(req: SafetyDemoRequest) -> ChatResponse:
    _validate_demo_request(req)
    storage.init_session(req.session_data)
    history = list(req.history)

    demo_key, demo = _pick_bad_safety_demo(req.example)
    session = storage.get_session() or {}
    session["safety_policy"] = _load_json_fixture(demo["policy"])
    storage.save(session)

    finance_reply = _load_text_fixture(demo["finance_reply"])
    user_message = f"Safety demo: run bad fixture `{demo_key}`."
    warning = _check_reply_with_tla_safety(user_message, finance_reply)
    reply = warning or (
        "The selected bad demo unexpectedly passed the safety gate. "
        "Check the fixture and policy before using this scenario for demos."
    )

    history.append({"role": "user", "content": f"Run bad safety demo: {demo['title']}"})
    history.append({"role": "assistant", "content": reply})
    return ChatResponse(reply=reply, session_data=storage.get_session() or {}, history=history[-30:])


def _semantic_check(req: SemanticCheckRequest) -> Dict[str, Any]:
    start = time.perf_counter()
    advice = req.finance_advice.strip()
    if not advice:
        raise SafetyInputError("finance_advice must not be empty")
    policy = SafetyPolicy.from_json(req.policy)
    run_policy_checker = bool(req.run_policy_checker)
    run_model_checker = _should_run_tlc() if req.run_model_checker is None else bool(req.run_model_checker)
    if not run_policy_checker and not run_model_checker:
        raise SafetyInputError("Enable Python policy checks, PlusCal / TLC, or both.")
    safety_input = (
        "User request:\n"
        f"{req.user_message.strip() or '(none)'}\n\n"
        "Finance agent response:\n"
        f"{advice}"
    )

    if req.benchmark is not None:
        if req.benchmark != "four_way_liquidity":
            raise SafetyInputError("Unknown model-checking benchmark.")
        if not run_model_checker:
            raise SafetyInputError("The branching benchmark requires PlusCal / TLC.")
        return _run_branching_benchmark(req, policy, safety_input, start)

    input_mode = "structured" if req.normalized_actions is not None else "semantic"
    if req.normalized_actions is not None:
        actions = load_actions(req.normalized_actions, allow_empty=True)
        transformer_usage: Dict[str, Any] = {"mode": "structured_stress_test"}
    else:
        transformer = OpenAIActionTransformer()
        try:
            actions = transformer.transform(safety_input)
        except SafetyInputError as exc:
            observability.log_event(
                logger,
                "api.semantic_check.extraction_failed",
                level=logging.WARNING,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            observability.log_event(
                logger,
                "api.semantic_check.end",
                level=logging.WARNING,
                status="extraction_failed",
                duration_ms=observability.elapsed_ms(start),
            )
            return _semantic_extraction_error_response(exc, transformer, run_policy_checker)
        transformer_usage = getattr(transformer, "last_usage_estimate", {})

    policy_findings = evaluate_policy(actions, policy) if run_policy_checker else []
    run_name = _semantic_run_name()
    run_id = observability.new_id("semantic")

    checker = TlaSafetyAgent(
        transformer=_PrecomputedActionTransformer(actions, transformer_usage),
        artifact_root=_safety_artifact_root(),
    )
    result = checker.check(
        safety_input,
        policy,
        run_name=run_name,
        run_policy_checker=run_policy_checker,
        run_model_checker=run_model_checker,
        run_id=run_id,
    )
    report = result.to_json()
    # The run directory is intentionally retained for local operators, but it
    # is not a browser capability.  Return only a non-addressable summary.
    public_pluscal = _public_checker_status(report["pluscal"])
    public_tlc = _public_checker_status(report["tlc"])
    response = {
        "safe_to_execute": result.safe_to_execute,
        "decision": result.decision,
        "input_mode": input_mode,
        "python_policy_enabled": run_policy_checker,
        "normalized_actions": dump_actions(actions),
        "python_policy_findings": [finding.to_json() for finding in policy_findings],
        "all_findings": report["findings"],
        "pluscal": public_pluscal,
        "tlc": public_tlc,
        "artifacts": {"generated": True},
        "transformer_usage": report["transformer_usage"],
        "observability": report["observability"],
    }
    observability.log_event(
        logger,
        "api.semantic_check.end",
        status="ok",
        action_count=len(actions),
        input_mode=input_mode,
        policy_finding_count=len(policy_findings),
        policy_checker_enabled=run_policy_checker,
        model_checker_enabled=run_model_checker,
        safe_to_execute=result.safe_to_execute,
        duration_ms=observability.elapsed_ms(start),
    )
    return response


def _run_branching_benchmark(
    req: SemanticCheckRequest,
    policy: SafetyPolicy,
    safety_input: str,
    start: float,
) -> Dict[str, Any]:
    rounds = 8
    decision_actions = [
        FinanceAction("transfer", 1, "reserve", "operations"),
        FinanceAction("transfer", 1, "checking", "savings"),
        FinanceAction("transfer", 1, "savings", "brokerage"),
        FinanceAction("transfer", 1, "brokerage", "checking"),
    ]
    final_action = FinanceAction("transfer", 1, "reserve", "payroll")
    run_name = _semantic_run_name()
    run_id = observability.new_id("branching")
    artifact_dir = Path(_safety_artifact_root()) / run_name
    generated = generate_branching_tla(
        decision_actions,
        final_action,
        policy,
        f"BranchingLiquidity_{run_name}",
        rounds=rounds,
    )
    tla_path, cfg_path = write_tla_artifacts(generated, artifact_dir)
    (artifact_dir / "finance_agent_output.txt").write_text(safety_input, encoding="utf-8")
    (artifact_dir / "policy.json").write_text(
        json.dumps(policy.to_json(), indent=2) + "\n",
        encoding="utf-8",
    )

    pluscal_start = time.perf_counter()
    pluscal = translate_pluscal(tla_path)
    pluscal_ms = observability.elapsed_ms(pluscal_start)
    (artifact_dir / "pcal_output.txt").write_text(pluscal.output, encoding="utf-8")

    tlc_ms = 0
    if pluscal.translated:
        tlc_start = time.perf_counter()
        tlc_result = run_tlc(tla_path, cfg_path)
        tlc_ms = observability.elapsed_ms(tlc_start)
        tlc = tlc_result.to_json()
        (artifact_dir / "tlc_output.txt").write_text(tlc_result.output, encoding="utf-8")
        stats = parse_tlc_statistics(tlc_result.output)
        counterexample = parse_tlc_counterexample_history(tlc_result.output)
    else:
        tlc = {
            "status": "skipped",
            "command": [],
            "returncode": None,
            "output": "TLC skipped because PlusCal translation did not complete.",
        }
        stats = {}
        counterexample = []

    findings: list[Dict[str, Any]] = []
    if tlc["status"] == "failed":
        invariant_violation = bool(counterexample)
        finding: Dict[str, Any] = {
            "code": "tlc_invariant_violation" if invariant_violation else "tlc_failed",
            "severity": "error",
            "message": summarize_tlc_failure(str(tlc["output"])),
        }
        if invariant_violation:
            finding["action_index"] = rounds + 1
            finding["counterexample_path"] = counterexample
        findings.append(finding)
    elif tlc["status"] in {"timeout", "not_configured"}:
        findings.append(
            {
                "code": f"tlc_{tlc['status']}",
                "severity": "error",
                "message": f"TLC {str(tlc['status']).replace('_', ' ')}.",
            }
        )
    elif not pluscal.translated:
        findings.append(
            {
                "code": f"pluscal_{pluscal.status}",
                "severity": "error",
                "message": "PlusCal translation did not complete.",
            }
        )

    safe_to_execute = pluscal.translated and tlc["status"] == "passed"
    complete_plans = len(decision_actions) ** rounds
    decision_plan = {
        "rounds": rounds,
        "branching_factor": len(decision_actions),
        "complete_plans": complete_plans,
        "expected_tree_states": (len(decision_actions) ** (rounds + 1) - 1)
        // (len(decision_actions) - 1),
        "choices": [
            {"name": name, **action.to_json()}
            for name, action in zip(("A", "B", "C", "D"), decision_actions)
        ],
        "final_action": final_action.to_json(),
        "tlc_statistics": stats,
        "counterexample_path": counterexample,
    }
    duration_ms = observability.elapsed_ms(start)
    observation = {
        "run_id": run_id,
        "duration_ms": duration_ms,
        "stage_durations_ms": {
            "evaluate_policy": 0,
            "pluscal": pluscal_ms,
            "tlc": tlc_ms,
        },
        "transformer_name": None,
        "action_count": rounds + 1,
        "policy_checker_enabled": False,
        "model_checker_enabled": True,
    }
    response = {
        "safe_to_execute": safe_to_execute,
        "decision": "safe" if safe_to_execute else "requires_user_decision",
        "input_mode": "branching",
        "python_policy_enabled": False,
        "normalized_actions": {"actions": []},
        "decision_plan": decision_plan,
        "python_policy_findings": [],
        "all_findings": findings,
        "pluscal": _public_checker_status(pluscal.to_json()),
        "tlc": _public_checker_status(tlc),
        "artifacts": {"generated": True},
        "transformer_usage": {"mode": "branching_benchmark"},
        "observability": observation,
    }
    (artifact_dir / "report.json").write_text(
        json.dumps(response, indent=2) + "\n",
        encoding="utf-8",
    )
    observability.log_event(
        logger,
        "api.semantic_check.end",
        status="ok",
        input_mode="branching",
        complete_plans=complete_plans,
        distinct_states=stats.get("distinct_states"),
        safe_to_execute=safe_to_execute,
        duration_ms=duration_ms,
    )
    return response


def _semantic_extraction_error_response(
    exc: SafetyInputError,
    transformer: OpenAIActionTransformer,
    run_policy_checker: bool = True,
) -> Dict[str, Any]:
    return {
        "safe_to_execute": False,
        "decision": "extraction_failed",
        "python_policy_enabled": run_policy_checker,
        "extraction_error": {
            "message": str(exc),
            "raw_model_output": getattr(transformer, "last_raw_content", ""),
        },
        "normalized_actions": {"actions": []},
        "python_policy_findings": [],
        "all_findings": [
            {
                "code": "semantic_action_extraction_failed",
                "severity": "error",
                "message": (
                    "The local model did not produce valid normalized action JSON, "
                    "so policy and TLC checks were not run."
                ),
            }
        ],
        "pluscal": {"status": "skipped"},
        "tlc": {"status": "skipped"},
        "artifacts": {},
        "transformer_usage": getattr(transformer, "last_usage_estimate", {}),
        "observability": {"status": "extraction_failed"},
    }


def _public_checker_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Remove command/output strings that can reveal local artifact paths."""

    return {
        "status": status.get("status", "unknown"),
        "returncode": status.get("returncode"),
    }


class _PrecomputedActionTransformer:
    def __init__(self, actions: list[FinanceAction], usage: Dict[str, Any]) -> None:
        self.actions = actions
        self.last_usage_estimate = usage

    def transform(self, finance_agent_output: str) -> list[FinanceAction]:
        return self.actions


def _semantic_run_name() -> str:
    return _timestamped_run_name("semantic")


def _safety_run_name() -> str:
    return _timestamped_run_name("safety")


def _timestamped_run_name(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{stamp}"


def _chat(req: ChatRequest) -> ChatResponse:
    storage.init_session(req.session_data)
    history = list(req.history)

    pending_reply = _handle_pending_safety_decision(req.message, history)
    if pending_reply is not None:
        observability.log_event(
            logger,
            "api.chat.pending_safety",
            status="handled",
        )
        return pending_reply

    client = openai_client()

    # Step 1: Route to agent(s)
    model = openai_model()
    with observability.operation(logger, "api.router.openai", model=model) as router_event:
        router_resp = client.chat.completions.create(
            **openai_chat_options(
                model=model,
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": req.message},
                ],
                max_tokens=200,
                temperature=0,
            )
        )
        try:
            routing = json.loads(router_resp.choices[0].message.content)
        except Exception as exc:
            observability.log_event(
                logger,
                "api.router.parse_failure",
                level=logging.WARNING,
                model=model,
                error_type=type(exc).__name__,
                duration_ms=router_event.elapsed_ms(),
            )
            routing = {"agents": ["budget"], "task": req.message}

        agents_to_call = routing.get("agents", ["budget"])
        task = routing.get("task", req.message)
        router_event.add_fields(
            selected_agents=agents_to_call,
            parsed_agent_count=len(agents_to_call) if isinstance(agents_to_call, list) else 0,
        )

    # Step 2: Call each specialist agent
    results: Dict[str, str] = {}
    for key in agents_to_call:
        if key in AGENT_MAP:
            fn, label = AGENT_MAP[key]
            with observability.operation(
                logger,
                "api.specialist_agent",
                agent=key,
                label=label,
            ):
                results[label] = fn(task)

    if not results:
        reply = "I'm not sure how to help with that. Try asking about budgeting, goals, investing, or debt."
    elif len(results) == 1:
        reply = next(iter(results.values()))
    else:
        combined = "\n\n".join(f"**{label}:**\n{resp}" for label, resp in results.items())
        synth = client.chat.completions.create(
            model=openai_model(),
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                {"role": "user", "content": req.message},
                {"role": "assistant", "content": combined},
                {"role": "user", "content": "Synthesize into one clear, helpful response."},
            ],
            max_tokens=1024,
        )
        reply = synth.choices[0].message.content or combined

    safety_reply = _check_reply_with_tla_safety(req.message, reply)
    safety_status = "blocked" if safety_reply is not None else "passed"
    if safety_reply is not None:
        reply = safety_reply

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    observability.log_event(
        logger,
        "api.chat.processed",
        selected_agents=list(results.keys()),
        requested_agents=agents_to_call,
        safety_status=safety_status,
    )
    return ChatResponse(
        reply=reply,
        session_data=storage.get_session() or {},
        history=history[-30:],
    )


def _pick_bad_safety_demo(example: Optional[str]) -> tuple[str, Dict[str, str]]:
    if example:
        key = example.strip()
        if key not in BAD_SAFETY_DEMOS:
            valid = ", ".join(sorted(BAD_SAFETY_DEMOS))
            raise HTTPException(
                status_code=400,
                detail=f"Unknown bad safety demo `{key}`. Valid examples: {valid}",
            )
        return key, BAD_SAFETY_DEMOS[key]
    key = random.choice(sorted(BAD_SAFETY_DEMOS))
    return key, BAD_SAFETY_DEMOS[key]


def _load_text_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _load_json_fixture(name: str) -> Dict[str, Any]:
    return json.loads(_load_text_fixture(name))


def _handle_pending_safety_decision(message: str, history: List[Dict[str, str]]) -> Optional[ChatResponse]:
    session = storage.get_session() or {}
    pending = session.get("pending_safety_review")
    if not pending:
        return None

    decision = _parse_safety_decision(message)
    if decision is None:
        reply = (
            "A safety warning from the previous finance response is still pending, so I did not process "
            "your latest message yet. Reply **continue** if you believe the warning is a false positive, "
            "or **stop** to terminate the proposed plan. After that, send your latest request again."
        )
    elif decision == "continue":
        reply = (
            "**Safety override recorded.** You marked the warning as a false positive, so I am continuing "
            "with the finance agent's proposed response.\n\n"
            f"{pending.get('approved_reply', '')}"
        )
        session.pop("pending_safety_review", None)
        storage.save(session)
    else:
        reply = (
            "**Plan terminated.** I will not continue with the finance agent's proposed action. "
            "You can ask for a safer alternative with a smaller budget or different allowed destination account."
        )
        session.pop("pending_safety_review", None)
        storage.save(session)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return ChatResponse(reply=reply, session_data=storage.get_session() or {}, history=history[-30:])


def _check_reply_with_tla_safety(user_message: str, finance_reply: str) -> Optional[str]:
    session = storage.get_session() or {}
    policy, policy_configured = _safety_policy_from_session(session)
    safety_input = (
        "User request:\n"
        f"{user_message}\n\n"
        "Finance agent response:\n"
        f"{finance_reply}"
    )

    checker = TlaSafetyAgent(
        transformer=_semantic_action_transformer(),
        artifact_root=_safety_artifact_root(),
    )
    start = time.perf_counter()
    safety_run_id = observability.new_id("safety")
    observability.log_event(
        logger,
        "api.safety_check.start",
        safety_run_id=safety_run_id,
        policy_configured=policy_configured,
    )
    with observability.scoped_context(safety_run_id=safety_run_id):
        try:
            result = checker.check(
                safety_input,
                policy,
                run_name=_safety_run_name(),
                run_model_checker=_should_run_tlc(),
                run_id=safety_run_id,
            )
        except SafetyInputError as exc:
            result = _recover_from_missing_actions_block(str(exc), user_message, policy)
        except Exception as exc:
            result = _failed_safety_result(str(exc))

    observability.log_event(
        logger,
        "api.safety_check.end",
        safety_run_id=result.observability.get("run_id", safety_run_id),
        status="passed" if result.safe_to_execute else "blocked",
        decision=result.decision,
        finding_count=len(result.findings),
        duration_ms=observability.elapsed_ms(start),
    )
    if result.safe_to_execute:
        return None

    session["pending_safety_review"] = {
        "approved_reply": finance_reply,
        "safety_report": result.to_json(),
    }
    storage.save(session)
    return _format_safety_warning(result, policy_configured)


def _recover_from_missing_actions_block(message: str, user_message: str, policy: SafetyPolicy) -> TlaSafetyAgentResult:
    if "finance-actions" not in message or "block" not in message:
        return _failed_safety_result(message, code="finance_output_protocol_violation")

    checker = TlaSafetyAgent(
        transformer=ExplicitRequestActionTransformer(),
        artifact_root=_safety_artifact_root(),
    )
    safety_run_id = observability.current_context().get("safety_run_id") or observability.new_id("safety")
    try:
        result = checker.check(
            user_message,
            policy,
            run_name=_timestamped_run_name("safety_recovered"),
            run_model_checker=_should_run_tlc(),
            run_id=str(safety_run_id),
        )
    except SafetyInputError:
        return _failed_safety_result(message, code="finance_output_protocol_violation")

    if not result.findings:
        return result

    protocol_finding = SafetyFinding(
        code="finance_output_protocol_violation",
        severity="warning",
        message=(
            "The configured deterministic parser did not find a finance-actions block. "
            "Concrete actions were recovered from the user request so policy violations could still be shown."
        ),
    )
    updated = replace(
        result,
        safe_to_execute=False,
        decision="requires_user_decision",
        findings=[protocol_finding, *result.findings],
        observability={
            **result.observability,
            "finding_codes": [protocol_finding.code, *result.observability.get("finding_codes", [])],
        },
    )
    (updated.artifact_dir / "report.json").write_text(
        json.dumps(updated.to_json(), indent=2) + "\n",
        encoding="utf-8",
    )
    return updated


def _safety_policy_from_session(session: Dict[str, Any]) -> tuple[SafetyPolicy, bool]:
    raw = session.get("safety_policy")
    if isinstance(raw, dict):
        try:
            return SafetyPolicy.from_json(raw), True
        except Exception:
            pass
    return SafetyPolicy.from_json({
        "budget": 0,
        "account_balances": {"__unconfigured__": 0},
        "allowed_destination_accounts": ["__no_allowed_destination_configured__"],
    }), False


def _should_run_tlc() -> bool:
    value = os.getenv("SAFETY_RUN_TLC", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _safety_artifact_root() -> str:
    configured = os.getenv("SAFETY_ARTIFACT_ROOT")
    if configured:
        return configured
    return "artifacts/safety-runs"


def _semantic_action_transformer():
    transformer = os.getenv("SAFETY_ACTION_TRANSFORMER", "semantic").strip().lower()
    if transformer == "block":
        return FinanceActionsBlockTransformer()
    if transformer == "explicit":
        return ExplicitRequestActionTransformer()
    if has_openai_api_key():
        return OpenAIActionTransformer()
    return FinanceActionsBlockTransformer()


def _parse_safety_decision(message: str) -> Optional[str]:
    text = message.strip().lower()
    if text in CONTINUE_WORDS or any(word in text for word in CONTINUE_WORDS if " " in word):
        return "continue"
    if text in STOP_WORDS:
        return "stop"
    return None


def _format_safety_warning(result: TlaSafetyAgentResult, policy_configured: bool) -> str:
    report = result.to_json()
    findings = report["findings"]
    lines = [
        "## TLA+ Safety Warning",
        "",
        "The finance agent proposed one or more concrete actions that did **not** pass the model-checking safety gate.",
    ]
    if not policy_configured:
        lines.extend([
            "",
            "**Safety policy is not configured.** Before approving real actions, set a budget, account balances, "
            "and allowed destination accounts in `session_data.safety_policy`.",
        ])
    lines.extend([
        "",
        "**Findings:**",
    ])
    for finding in findings:
        action = f" action {finding['action_index']}" if "action_index" in finding else ""
        lines.append(f"- `{finding['code']}`{action}: {finding['message']}")
    lines.extend([
        "",
        f"**PlusCal:** `{report['pluscal']['status']}`",
        f"**TLC:** `{report['tlc']['status']}`",
        f"**Artifacts:** `{report['artifacts']['directory']}`",
        "",
        "Reply **continue** if you believe this is a false positive and want to proceed, or reply **stop** to terminate this plan.",
    ])
    return "\n".join(lines)


def _failed_safety_result(message: str, code: str = "safety_checker_error") -> TlaSafetyAgentResult:
    artifact_root = Path(_safety_artifact_root())
    run_id = str(observability.current_context().get("safety_run_id") or observability.new_id("safety"))
    return TlaSafetyAgentResult(
        safe_to_execute=False,
        decision="requires_user_decision",
        findings=[
            SafetyFinding(
                code=code,
                severity="error",
                message=f"The safety checker could not complete: {message}",
            )
        ],
        artifact_dir=artifact_root,
        tla_path=artifact_root,
        cfg_path=artifact_root,
        pluscal={"status": "not_run", "command": [], "returncode": None, "output": message},
        tlc={"status": "not_run", "command": [], "returncode": None, "output": message},
        transformer_usage={},
        observability={
            "run_id": run_id,
            "started_at": observability.now_iso(),
            "duration_ms": 0,
            "stage_durations_ms": {},
            "transformer_name": None,
            "action_count": 0,
            "finding_codes": [code],
            "model_checker_enabled": False,
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve static files for local development.
public_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if os.path.isdir(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="static")
