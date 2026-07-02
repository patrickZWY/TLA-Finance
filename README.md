# AutomataSeal (TLA-Finance)

Local finance safety workbench and personal finance agent prototype. The current
primary demo is a browser workbench that takes ambiguous finance prose,
normalizes it into concrete action JSON with an OpenAI-compatible model, and
checks the actions against deterministic Python policy checks plus an optional
PlusCal/TLA+ model-checking pass.

This project is local-development/demo software. It does not connect to banks,
brokerages, or payment systems, and it does not execute real transactions. Any
investment examples are educational, not licensed financial advice.

## Current Demo Path

The frontend served from `public/index.html` is the **Finance Safety Workbench**.
It is focused on one flow:

```text
Browser workbench
  -> POST /api/semantic-check
  -> semantic action extraction
  -> canonical finance action JSON
  -> Python policy mirror
  -> generated PlusCal/TLA+ artifacts
  -> optional TLC model checker
  -> structured result shown in the UI
```

The workbench lets you:

- choose or write ambiguous finance advice,
- edit safety invariants in the browser,
- inspect normalized actions from the model,
- see Python policy findings,
- see PlusCal/TLC status and artifact paths,
- inspect raw model output when extraction fails.

The older multi-agent personal finance assistant still exists through
`/api/chat` and `main.py`, but it is not the current first-screen frontend.

## Quick Start

Create an environment and install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure one LLM path in `.env`.

Paid OpenAI API:

```sh
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

Local OpenAI-compatible model, recommended for the demo:

```sh
ollama pull qwen3:4b
ollama serve
```

Then set:

```sh
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen3:4b
OPENAI_REASONING_EFFORT=none
SAFETY_RUN_TLC=1
```

Start the local app:

```sh
python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. If Java/TLA+ tools are not configured yet,
uncheck **Run PlusCal/TLC** in the UI for extractor and Python-policy smoke
tests, or set up TLA+ with [docs/tla_setup_macos.md](docs/tla_setup_macos.md).

## TLA+ Tools

Full model-checking requires Java plus `tla2tools.jar`. The checker finds the
jar from either:

- `TLAPLUS_JAR=/path/to/tla2tools.jar`
- `TLA_HOME=/path/to/directory-containing-tla2tools.jar`

See [docs/tla_setup_macos.md](docs/tla_setup_macos.md) for a macOS setup.
Without these tools, the app can still generate artifacts and run Python policy
checks, but TLC-backed runs report `not_configured`.

## Safety Policy And Actions

The safety policy schema is:

```json
{
  "budget": 700,
  "max_individual_action_amount": 400,
  "account_balances": {
    "checking": 1000,
    "brokerage": 0,
    "savings": 300
  },
  "allowed_destination_accounts": ["brokerage", "savings"],
  "allowed_action_types": ["buy", "sell", "swap", "deposit", "transfer", "withdraw"]
}
```

The canonical action schema is:

```json
{
  "actions": [
    {
      "action": "transfer",
      "amount": 350,
      "from": "checking",
      "to": "brokerage"
    }
  ]
}
```

The Python policy layer checks:

- action type is allowed,
- amount is positive,
- destination is allowlisted,
- total planned outflow does not exceed `budget`,
- no action exceeds `max_individual_action_amount`,
- debit source accounts exist,
- source balances do not go negative as actions are applied in order.

The PlusCal/TLC layer checks the generated finite-state model for the same
invariants and makes order-sensitive failures visible in model-checker output.

## Useful Commands

Run the safety CLI on structured fixture actions without requiring TLA+ tools:

```sh
python3 -m safety.cli check \
  --actions fixtures/actions.safe.json \
  --policy fixtures/policy.dev.json \
  --skip-tlc \
  --auto-decision stop
```

Run semantic extraction over prose using the configured OpenAI-compatible model:

```sh
python3 -m safety.cli check \
  --actions fixtures/finance_reply.complex_bad.destination_and_budget.md \
  --policy fixtures/policy.complex_budget700_item400.json \
  --transformer openai \
  --skip-tlc \
  --auto-decision stop
```

Run the terminal finance assistant:

```sh
python3 main.py
```

The CLI assistant persists local data in `finance_data.json`, which is ignored
by git. The FastAPI app uses request/session data from the browser instead of
writing that file during normal API requests.

Run tests:

```sh
python3 -m unittest discover -s tests
```

For a faster local safety pass that intentionally skips TLC:

```sh
SAFETY_RUN_TLC=0 python3 -m unittest discover -s tests
```

## API Surface

FastAPI is defined in `api/index.py`.

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Health check. |
| `POST /api/semantic-check` | Workbench endpoint for semantic extraction, policy checks, and optional TLC. |
| `POST /api/chat` | Multi-agent finance chat route with safety gate integration. |
| `POST /api/demo/bad-suggestion` | Injects known bad fixture replies through the safety gate for demos. |
| `/` | Static Finance Safety Workbench from `public/index.html`. |

The API has local CORS and host checks plus simple in-process rate limits for
demo endpoints.

## Finance Agents

The repo still includes four specialist agents behind the API/CLI orchestrator:

| Agent | Handles |
| --- | --- |
| Budget | Transactions, budget limits, spending summaries, category breakdowns. |
| Goal | Savings goals, deadlines, progress updates, monthly savings plans. |
| Investment | Risk profiles, ETF-style allocation examples, compound-growth projections. |
| Debt | Debt tracking, snowball/avalanche payoff plans, strategy comparisons. |

Each specialist uses the shared JSON-mode `agents/tool_loop.py`, which keeps
tool execution provider-agnostic for OpenAI-compatible chat APIs.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | unset | Paid OpenAI API key. Not required when `OPENAI_BASE_URL` is set. |
| `OPENAI_BASE_URL` / `LOCAL_LLM_BASE_URL` | unset | OpenAI-compatible local endpoint, such as Ollama at `http://localhost:11434/v1`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat/extraction model name. |
| `OPENAI_JSON_MODE` | `1` | Set to `0` if a local server rejects OpenAI JSON-mode `response_format`. |
| `OPENAI_REASONING_EFFORT` | unset | Set to `none` for local thinking/reasoning models that support it. |
| `SAFETY_RUN_TLC` | `1` | Enables PlusCal/TLC in routes that do not specify `run_model_checker`. |
| `SAFETY_ACTION_TRANSFORMER` | `semantic` | API chat transformer. Supports `semantic`, `block`, and `explicit`. |
| `SAFETY_ARTIFACT_ROOT` | `artifacts/safety-runs` | Directory for generated inputs, TLA/CFG files, tool output, and reports. |
| `SAFETY_ARTIFACT_RETENTION_HOURS` | `24` | Startup cleanup age for old safety run directories. |
| `TLAPLUS_JAR` / `TLA_HOME` | unset | Location of `tla2tools.jar`. |
| `SAFETY_TLA_TIMEOUT_SECONDS` | `60` | Default PlusCal/TLC subprocess timeout. |
| `SAFETY_PLUSCAL_TIMEOUT_SECONDS` / `SAFETY_TLC_TIMEOUT_SECONDS` | unset | Per-tool timeout overrides. |
| `ALLOWED_ORIGINS` | local origins | Comma-separated CORS origin allowlist. |
| `ALLOWED_HOSTS` | local hosts | Comma-separated trusted host allowlist. |
| `PUBLIC_HOSTNAME` / `CLOUDFLARE_HOSTNAME` / `CF_HOSTNAME` | unset | Adds a public HTTPS origin and host. |
| `OBSERVABILITY_ENABLED` | `1` | Disable structured event emission with `0`, `false`, `no`, or `off`. |
| `OBSERVE_PAYLOADS` | `0` | Set to `1` to log sensitive prompts, replies, and tool arguments. |
| `LOG_FORMAT` | `plain` | Use `json` for machine-parseable logs. |
| `LOG_LEVEL` | `INFO` | Python logging level used by entrypoints. |

Request-size limits are also configurable with `API_MAX_*` variables. See
`DEFAULT_REQUEST_LIMITS` in [api/index.py](api/index.py).

## Project Layout

```text
api/index.py                  FastAPI app, middleware, routes, static frontend
public/index.html             Finance Safety Workbench UI
safety/agent.py               TlaSafetyAgent pipeline
safety/models.py              FinanceAction and SafetyPolicy models
safety/transformer.py         JSON, fenced-block, explicit, and OpenAI action transformers
safety/validator.py           Deterministic policy mirror
safety/tla_generator.py       PlusCal/TLA+ and TLC config generator
safety/checker.py             PlusCal translator and TLC subprocess runner
safety/cli.py                 `python -m safety.cli check`
agents/                       Budget, goal, investment, debt, storage, tool loop
fixtures/                     Safe and unsafe policies, actions, and prose examples
tests/                        unittest coverage for API, safety, config, observability
docs/                         Deeper setup and design notes
scripts/run_cloudflare_demo.sh Local Cloudflare Access demo helper
main.py                       Terminal multi-agent finance assistant
observability.py              Structured event facade and logging sink
config.py                     Runtime configuration helpers
```

## Deeper Docs

- [docs/local_llm_semantic_extraction.md](docs/local_llm_semantic_extraction.md)
  covers the local Ollama semantic extraction demo.
- [docs/local_llm_safety_workbench_design.md](docs/local_llm_safety_workbench_design.md)
  describes the current workbench architecture and failure modes.
- [docs/safety_gate_mvp.md](docs/safety_gate_mvp.md) explains the safety agent,
  fixture flows, and policy invariants.
- [docs/cloudflare_one_demo.md](docs/cloudflare_one_demo.md) covers the
  invite-only Cloudflare Access demo path.
