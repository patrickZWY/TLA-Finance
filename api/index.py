import copy
import json
import logging
import os
import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

from agents import budget_agent, debt_agent, goal_agent, investment_agent, storage
from config import has_openai_api_key, normalize_openai_api_key, openai_model
import observability
from safety.agent import TlaSafetyAgentResult
from safety.models import SafetyInputError, SafetyPolicy
from safety.transformer import (
    ExplicitRequestActionTransformer,
    FinanceActionsBlockTransformer,
    OpenAIActionTransformer,
)
from safety.agent import TlaSafetyAgent
from safety.validator import SafetyFinding

normalize_openai_api_key()
observability.configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="Personal Finance Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
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
    history: List[Dict[str, str]] = []


class ChatResponse(BaseModel):
    reply: str
    session_data: Dict[str, Any]
    history: List[Dict[str, str]]


class SafetyDemoRequest(BaseModel):
    session_data: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = []
    example: Optional[str] = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    request_id = observability.new_id("req")
    start = time.perf_counter()
    with observability.scoped_context(request_id=request_id):
        observability.log_event(
            logger,
            "api.chat.start",
            history_len=len(req.history),
            has_session_data=req.session_data is not None,
            message=observability.payload(req.message),
        )
        try:
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


@app.post("/api/demo/bad-suggestion")
def demo_bad_suggestion(req: SafetyDemoRequest) -> ChatResponse:
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

    client = OpenAI()

    # Step 1: Route to agent(s)
    model = openai_model()
    with observability.operation(logger, "api.router.openai", model=model) as router_event:
        router_resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": req.message},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0,
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
    if "finance-actions JSON block" not in message:
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
