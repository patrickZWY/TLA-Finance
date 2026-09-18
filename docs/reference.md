# Reference

Detailed material that used to live in the README: API routes, the policy and
action schemas, CLI commands, environment variables, and the project layout.
For setup, start at the [README](../README.md).

## API Surface

FastAPI is defined in [`api/index.py`](../api/index.py).

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Health check. |
| `POST /api/semantic-check` | Legacy prose path: semantic extraction, policy checks, and optional TLC. |
| `POST /api/bounded-workbench` | Closed FSIR path: typed validation, bounded lowering, hash-bound TLC evidence. See [bounded_agent_workbench.md](bounded_agent_workbench.md). |
| `POST /api/chat` | Multi-agent finance chat route with safety gate integration. |
| `POST /api/demo/bad-suggestion` | Injects known bad fixture replies through the safety gate for demos. |
| `/` | Static Finance Safety Workbench from `public/index.html`. |

The two trust paths:

```text
Legacy prose path
  -> POST /api/semantic-check
  -> semantic action extraction
  -> canonical finance action JSON
  -> Python policy mirror
  -> generated PlusCal/TLA+ artifacts
  -> optional TLC model checker

Closed bounded path
  -> POST /api/bounded-workbench
  -> typed FSIR v0.1 validation
  -> bounded FSIR-to-TLA+ lowering
  -> hash-bound TLC evidence and source-linked counterexample
  -> fail-closed approval controls
```

The prose path is a heuristic projection and grants no execution authority.
The bounded path accepts only a frozen corpus case or a complete canonical
FSIR document. Its supported executable subset is intentionally narrow;
unsupported inputs, stale or malformed evidence, and contract drift fail
closed.

The API has local CORS and host checks plus simple in-process rate limits for
demo endpoints. Request-size limits are configurable with `API_MAX_*`
variables; see `DEFAULT_REQUEST_LIMITS` in `api/index.py`.

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

The typed FSIR path has a deterministic bounded direct-TLA+ lowerer. It
supports sequences, mutually exclusive plans, guarded cash/asset updates, and
partial-order transfer-settlement lifecycles, with stable source maps,
artifact/tool/input hashes, and normalized TLC counterexamples. See
[fsir_lowering_v0.1.md](fsir_lowering_v0.1.md).

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

Run tests, with and without TLC:

```sh
python3 -m unittest discover -s tests
SAFETY_RUN_TLC=0 python3 -m unittest discover -s tests
```

Run the reviewer evidence suite, the semantic extractor benchmark, the strict
CI gate, and the multi-model matrix (details in
[research_eval_workflow.md](research_eval_workflow.md)):

```sh
scripts/run_evidence_suite.sh
python3 scripts/semantic_eval.py --transformer gold
python3 scripts/semantic_eval.py \
  --transformer gold \
  --min-pass-rate 1 \
  --min-schema-rate 1 \
  --min-exact-action-rate 1 \
  --min-finding-code-rate 1
python3 scripts/run_model_eval_matrix.py
```

## Finance Agents

The repo still includes four specialist agents behind the API/CLI orchestrator
(`/api/chat` and `main.py`). They are not the current first-screen frontend.

| Agent | Handles |
| --- | --- |
| Budget | Transactions, budget limits, spending summaries, category breakdowns. |
| Goal | Savings goals, deadlines, progress updates, monthly savings plans. |
| Investment | Risk profiles, ETF-style allocation examples, compound-growth projections. |
| Debt | Debt tracking, snowball/avalanche payoff plans, strategy comparisons. |

Each specialist uses the shared JSON-mode `agents/tool_loop.py`, which keeps
tool execution provider-agnostic for OpenAI-compatible chat APIs.

## Environment Variables

`api/index.py` and `main.py` load `.env` through `python-dotenv`.

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | unset | Paid OpenAI API key. Not required when `OPENAI_BASE_URL` is set. |
| `OPENAI_BASE_URL` / `LOCAL_LLM_BASE_URL` | unset | OpenAI-compatible local endpoint, such as Ollama at `http://localhost:11434/v1`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat/extraction model name. |
| `OPENAI_JSON_MODE` | `1` | Set to `0` if a local server rejects OpenAI JSON-mode `response_format`. |
| `OPENAI_REASONING_EFFORT` | unset | Set to `none` for local thinking/reasoning models that support it. |
| `OPENAI_DISABLE_THINKING` | `0` | Set to `1` for Qwen3/vLLM JSON-only calls; sends `chat_template_kwargs.enable_thinking=false`. |
| `OPENAI_TIMEOUT_SECONDS` | `120` | Per-request timeout for OpenAI-compatible endpoints. |
| `OPENAI_MAX_RETRIES` | `1` | Automatic SDK retries after the initial request; set to `0` to fail immediately. |
| `SAFETY_RUN_TLC` | `1` | Enables PlusCal/TLC in routes that do not specify `run_model_checker`. |
| `SAFETY_ACTION_TRANSFORMER` | `semantic` | API chat transformer. Supports `semantic`, `block`, and `explicit`. |
| `SAFETY_ARTIFACT_ROOT` | `artifacts/safety-runs` | Directory for generated inputs, TLA/CFG files, tool output, and reports. |
| `SAFETY_ARTIFACT_RETENTION_HOURS` | `24` | Startup cleanup age for old safety run directories. |
| `TLAPLUS_JAR` / `TLA_HOME` | unset | Location of `tla2tools.jar`, or a directory containing it. |
| `SAFETY_TLA_TIMEOUT_SECONDS` | `60` | Default PlusCal/TLC subprocess timeout. |
| `SAFETY_PLUSCAL_TIMEOUT_SECONDS` / `SAFETY_TLC_TIMEOUT_SECONDS` | unset | Per-tool timeout overrides. |
| `ALLOWED_ORIGINS` | local origins | Comma-separated CORS origin allowlist. |
| `ALLOWED_HOSTS` | local hosts | Comma-separated trusted host allowlist. |
| `PUBLIC_HOSTNAME` / `PUBLIC_DEMO_HOSTNAME` / `CLOUDFLARE_HOSTNAME` / `CF_HOSTNAME` | unset | Adds public HTTPS origins and hosts. |
| `OBSERVABILITY_ENABLED` | `1` | Disable structured event emission with `0`, `false`, `no`, or `off`. |
| `OBSERVE_PAYLOADS` | `0` | Set to `1` to log sensitive prompts, replies, and tool arguments. |
| `LOG_FORMAT` | `plain` | Use `json` for machine-parseable logs. |
| `LOG_LEVEL` | `INFO` | Python logging level used by entrypoints. |

If the browser shows `Invalid host header`, the app is being reached through a
hostname that is not trusted by FastAPI. Restart the app with that hostname in
`ALLOWED_HOSTS`, or set `PUBLIC_DEMO_HOSTNAME`/`PUBLIC_HOSTNAME` for the public
site hostname:

```sh
export PUBLIC_DEMO_HOSTNAME=demo.example.com
export CLOUDFLARE_HOSTNAME=live-demo.example.com
python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

## Project Layout

```text
api/index.py                  FastAPI app, middleware, routes, static frontend
public/index.html             Finance Safety Workbench UI
safety/agent.py               TlaSafetyAgent pipeline
safety/models.py              FinanceAction and SafetyPolicy models
safety/fsir.py                Closed typed FSIR v0.1 models, validation, and legacy adapters
safety/fsir_lowering.py       Reviewed bounded FSIR-to-TLA+ lowering and evidence validation
safety/bounded_workbench.py   Closed corpus/FSIR workbench contract and controls
safety/phase4a_semantic_oracles.py  Closed semantic-mutant oracle registry
safety/transformer.py         JSON, fenced-block, explicit, and OpenAI action transformers
safety/validator.py           Deterministic policy mirror
safety/tla_generator.py       PlusCal/TLA+ and TLC config generator
safety/checker.py             PlusCal translator and TLC subprocess runner
safety/cli.py                 `python -m safety.cli check`
agents/                       Budget, goal, investment, debt, storage, tool loop
fixtures/                     Safe and unsafe policies, actions, and prose examples
benchmarks/                   Frozen phase 3B corpus and phase 4A materializer evidence
contracts/                    Reference-audit contract for the core.30 boundary
tests/                        unittest coverage for API, safety, config, observability
docs/                         Deeper setup and design notes
scripts/run_cloudflare_demo.sh Local Cloudflare demo helper
scripts/run_vast_backend.sh   Remote vLLM backend helper
scripts/run_evidence_suite.sh Reviewer evidence suite
scripts/materialize_phase3b_mutants.py  Deterministic 32-mutant materializer/replay
main.py                       Terminal multi-agent finance assistant
observability.py              Structured event facade and logging sink
config.py                     Runtime configuration helpers
```

## Other Docs

- [local_llm_semantic_extraction.md](local_llm_semantic_extraction.md): the local Ollama semantic extraction demo.
- [local_llm_safety_workbench_design.md](local_llm_safety_workbench_design.md): workbench architecture and failure modes.
- [local_semantic_testing.md](local_semantic_testing.md): testing prose cases without a live model call.
- [phase4a_semantic_mutant_materializer.md](phase4a_semantic_mutant_materializer.md): deterministic execution and replay of the 32 frozen corpus semantic mutants.
- [research_eval_roadmap.md](research_eval_roadmap.md) and [speedup_options.md](speedup_options.md): reviewer roadmap and performance notes.
- [fixes.md](fixes.md): dated troubleshooting log.
