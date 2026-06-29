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
├── main.py                  # CLI entry point
└── requirements.txt
```

---

## Run locally

```bash
# 1. Install
pip install -r requirements.txt

# 2. Set API key
cp .env.example .env
# edit .env -> OPENAI_API_KEY=your_key
# optional: OPENAI_MODEL=gpt-4o-mini

# 3. Local web app
python3 -m uvicorn api.index:app --port 8000
# open http://localhost:8000

# 3b. Terminal CLI
python3 main.py
```

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
