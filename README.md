# AutomataSeal

> AI-powered personal finance agent with a formal safety gate — budget, goals, investments, and debt in one chat.

This project is currently local-development only. The frontend is served by the
local FastAPI app and is available only while you run the local server.

---

## Overview

AutomataSeal is a multi-agent AI system that acts as your personal financial advisor. Type naturally — it routes your message to the right specialist, runs the numbers, and responds in plain language.

```
"I spent $120 on groceries"           → Budget Agent logs the expense
"Save $10k for a house by 2027"       → Goal Agent calculates monthly savings needed
"Invest $500/month, moderate risk"    → Investment Agent builds a portfolio plan
"Credit card $5k at 22% APR"          → Debt Agent runs snowball vs avalanche
```

Before any **concrete financial action** (transfer, buy, withdraw, etc.) is executed, it passes through a **TLA+ / PlusCal finite-state safety gate** that model-checks the action against your declared policy.

---

## Finance Agents

| Agent | What it handles |
|---|---|
| **Budget** | Log income & expenses, category limits, monthly summaries |
| **Goal Planner** | Savings goals with deadlines, required monthly savings, progress tracking |
| **Investment Guide** | Risk profiling, ETF/index fund allocations (VTI, VXUS, BND), compound growth |
| **Debt Eliminator** | Snowball vs avalanche payoff plans, interest saved, payoff timelines |

---

## TLA+ Safety Gate

Every proposed action the AI generates is passed through a formal verification pipeline before being approved:

```
Finance Agent output
        │
        ▼
  LLM Action Extractor   reads prose semantically and emits canonical actions
        │
        ▼
  Policy Validator       checks amounts, accounts, action types against your policy
        │
        ▼
  TLA+ / PlusCal Gen     generates a formal spec of the proposed state transitions
        │
        ▼
  TLC Model Checker      exhaustively checks all reachable states for invariant violations
        │
        ▼
  Safe to execute?  ──yes──▶  proceed
                    ──no───▶  block + show findings, ask user to confirm or stop
```

**What the safety policy covers:**

| Field | Description |
|---|---|
| `budget` | Maximum total spend across all actions |
| `max_individual_action_amount` | Cap on any single action |
| `account_balances` | Starting balances used in the state machine |
| `allowed_destination_accounts` | Whitelist of permitted transfer targets |
| `allowed_action_types` | Permitted verbs: `buy`, `sell`, `swap`, `deposit`, `transfer`, `withdraw` |

The extractor maps varied finance vocabulary such as “purchase,” “move,”
“wire,” “liquidate,” or “rebalance” into the canonical action schema:
`buy`, `sell`, `swap`, `deposit`, `transfer`, and `withdraw`.

The TLA+ spec models your accounts as finite automata — each canonical action transitions the state, and TLC verifies that no sequence of actions violates your constraints (e.g. overdraft, unauthorized destination, budget exceeded).

Artifacts (`.tla`, `.cfg`, TLC output) are saved per run under `artifacts/safety-runs/`.
They are not served over HTTP. The API removes old run directories on startup;
set `SAFETY_ARTIFACT_RETENTION_HOURS` to tune the default 24-hour retention.

---

## Observability

The app emits structured, stdlib-only observability events through
`observability.py`. Callers use a small facade (`log_event`, `operation`,
`timed_stage`, and scoped context), while the emission backend is isolated
behind an `EventSink`. The default sink writes to Python logging, and a future
OpenTelemetry exporter should be added as a new sink instead of changing API,
agent, or safety-gate business logic.

Useful environment variables:

| Variable | Default | Description |
|---|---:|---|
| `OBSERVABILITY_ENABLED` | `1` | Set to `0`, `false`, `no`, or `off` to disable event emission |
| `OBSERVE_PAYLOADS` | `0` | Set to `1` to include sensitive payload fields; otherwise prompts, replies, messages, tool args, and similar text are redacted |
| `LOG_FORMAT` | `plain` | Use `json` for machine-parseable log records |
| `LOG_LEVEL` | `INFO` | Python logging level used by explicit entrypoint logging setup |

Application entrypoints configure logging explicitly. Library-style helpers do
not install root handlers implicitly, which keeps the observability layer
replaceable and avoids surprising host applications.

Safety reports include an additive `observability` section with run metadata,
stage durations, transformer name, action count, finding codes, and whether TLC
was enabled.

---

## Project structure

```
AutomataSeal/
├── api/index.py             # FastAPI backend — localhost
├── agents/
│   ├── budget_agent.py
│   ├── goal_agent.py
│   ├── investment_agent.py
│   ├── debt_agent.py
│   ├── tla_safety_agent.py  # Safety gate entry point
│   ├── tool_loop.py         # Shared JSON-mode agentic loop
│   └── storage.py           # File storage for CLI, in-memory session storage for API
├── safety/
│   ├── agent.py             # TlaSafetyAgent — full pipeline orchestrator
│   ├── models.py            # FinanceAction, SafetyPolicy data models
│   ├── tla_generator.py     # PlusCal / TLA+ spec generator
│   ├── checker.py           # pcal.trans + TLC runner
│   ├── transformer.py       # Parses finance-agent prose → structured actions
│   └── validator.py         # Policy invariant checks, SafetyFinding
├── public/index.html        # Chat UI
├── observability.py         # Structured event facade and logging sink
├── main.py                  # CLI entry point
└── requirements.txt
```

---

## Run locally

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure an LLM
cp .env.example .env
# paid path: set OPENAI_API_KEY and optionally OPENAI_MODEL
# local demo path: set OPENAI_BASE_URL and OPENAI_MODEL for an OpenAI-compatible local server

# 3. Local web app
python3 -m uvicorn api.index:app --port 8000
# open http://localhost:8000

# 3b. Terminal CLI
python3 main.py
```

### Local LLM demo mode

For a no-paid-API demo, use Ollama with `qwen3:4b`:

```sh
ollama pull qwen3:4b
ollama serve
```

Then start the app with:

```sh
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_MODEL=qwen3:4b
export OPENAI_REASONING_EFFORT=none
export SAFETY_RUN_TLC=1
export SAFETY_TLA_TIMEOUT_SECONDS=60
python3 -m uvicorn api.index:app --port 8000
```

Open `http://localhost:8000`. The workbench lets you choose an ambiguous
finance message, edit the policy invariants, run local semantic extraction, and
then see Python policy findings plus TLC output.

The app supplies a dummy local API key when `OPENAI_BASE_URL` is set. See
`docs/local_llm_safety_workbench_design.md` for the workbench architecture and
`docs/local_llm_semantic_extraction.md` for successful demo scenarios and
troubleshooting notes.

### Invite-only Cloudflare demo

For a temporary public demo, keep FastAPI bound to loopback and publish it with
a named Cloudflare Tunnel protected by Cloudflare Access:

```sh
export CLOUDFLARE_HOSTNAME=automata-demo.example.com
export TLAPLUS_JAR=/path/to/tla2tools.jar
bash scripts/run_cloudflare_demo.sh
cloudflared tunnel run <tunnel-name>
```

The app uses env-driven CORS/host validation (`ALLOWED_ORIGINS`,
`ALLOWED_HOSTS`) plus in-process rate limits for the demo endpoints. The full
Cloudflare Access setup and acceptance checklist are in
`docs/cloudflare_one_demo.md`.

---

## Example prompts

**Budget**
- `I spent $85 on groceries and $45 on transport today`
- `Set a $300/month limit for dining out`

**Goals**
- `I want to save $10,000 for an emergency fund by June 2027`
- `I have $2,000 saved toward my vacation goal — update my progress`

**Investing**
- `I'm 27, aggressive risk, can invest $600/month for 30 years`
- `If I invest $300/month for 20 years at 7%, what will I have?`

**Debt**
- `I have a Chase card with $4,500 at 22% APR, $90 minimum`
- `Compare snowball vs avalanche with $150 extra per month`

---

## Tech stack

- **LLM** — OpenAI API (`OPENAI_MODEL`, default `gpt-4o-mini`)
- **Safety** — TLA+ / PlusCal + TLC model checker
- **Backend** — FastAPI (Python)
- **Frontend** — Vanilla HTML/CSS/JS, [marked.js](https://marked.js.org)
- **Local app** — FastAPI serves the vanilla frontend from `public/`
- **CLI** — [Rich](https://github.com/Textualize/rich)
- **Observability** — Structured Python logging via a replaceable event sink
