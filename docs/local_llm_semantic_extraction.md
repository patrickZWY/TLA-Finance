# Local LLM Semantic Extraction

Use this when the demo goal is to prove that ambiguous finance language can be
read into canonical action JSON without a paid API.

## Configure

Recommended default for this demo: `qwen3:4b` through Ollama. It is small
enough for a laptop-class local run and is a better fit for JSON extraction
than the tiny 1B-class models.

```sh
ollama pull qwen3:4b
ollama serve
```

Then set:

```sh
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL="qwen3:4b"
export OPENAI_REASONING_EFFORT="none"
export SAFETY_RUN_TLC="1"
```

`OPENAI_API_KEY` is optional for local mode. The app supplies a dummy key when
`OPENAI_BASE_URL` is present.

If your local server rejects `response_format={"type":"json_object"}`, disable
strict JSON mode:

```sh
export OPENAI_JSON_MODE=0
```

Keep JSON mode enabled when the server supports it. The safety gate still parses
the model response as JSON either way.

`OPENAI_REASONING_EFFORT=none` is useful for thinking-capable local models on
OpenAI-compatible endpoints. For Ollama on `localhost:11434`, the transformer
also uses the native `/api/chat` structured-output path with `think: false`.
This matters for `qwen3:4b`: without disabling thinking, the model can spend
the output budget in a `thinking` field and return empty or malformed JSON
content.

Fallback models if `qwen3:4b` is too slow:

- `llama3.2:3b`: smaller and fast, usually decent at instruction-following.
- `qwen3:1.7b`: very small, but expect more JSON mistakes.
- `phi4-mini`: similar download size to `qwen3:4b`, worth trying if Qwen
  produces malformed JSON on your machine.

## Check Prose Through The Safety Gate

This runs only semantic extraction plus policy/TLA checking. It does not require
the chat UI or the finance specialist agents.

```sh
python3 -m safety.cli check \
  --actions fixtures/finance_reply.complex_bad.destination_and_budget.md \
  --policy fixtures/policy.complex_budget700_item400.json \
  --transformer openai \
  --auto-decision stop
```

For a faster extractor-only smoke test without PlusCal/TLC:

```sh
python3 -m safety.cli check \
  --actions fixtures/finance_reply.flow_bad.buy_before_transfer.md \
  --policy fixtures/policy.flow_budget600_item300.json \
  --transformer openai \
  --skip-tlc \
  --auto-decision stop
```

Inspect the generated action JSON:

```sh
cat artifacts/safety-runs/*/normalized_actions.json
```

The demo is meaningful when `normalized_actions.json` captures the intended
money movement from prose and the report findings match the policy violation.

## Run The Local UI

```sh
OPENAI_BASE_URL=http://localhost:11434/v1 \
OPENAI_MODEL=qwen3:4b \
OPENAI_REASONING_EFFORT=none \
SAFETY_RUN_TLC=1 \
python3 -m uvicorn api.index:app --port 8000
```

Open `http://localhost:8000`.

The workbench has three demo surfaces:

- Ambiguous finance message: choose a prefilled case or type your own prose.
- Security invariants: edit budget, per-action cap, balances, allowed
  destinations, and allowed action types.
- Result: inspect local-model normalized actions, Python policy findings, TLC
  status/output, artifacts, and raw local-model output when extraction fails.

Use this concrete plan with the complex policy:

```text
Send 350 from checking to brokerage, set aside 350 from checking for savings,
and wire 50 from checking to Alex for tickets.
```

The local LLM should extract three transfer actions. The safety gate should
flag the unauthorized destination and budget violation under the complex demo
policy.

Expected normalized actions:

```json
{
  "actions": [
    {"action": "transfer", "amount": 350, "from": "checking", "to": "brokerage"},
    {"action": "transfer", "amount": 350, "from": "checking", "to": "savings"},
    {"action": "transfer", "amount": 50, "from": "checking", "to": "Alex"}
  ]
}
```

Expected Python findings:

- `disallowed_destination` for `Alex`
- `budget_exceeded` when total planned outflow reaches `750` over a `700`
  budget

For an order-sensitive TLC demo, use:

```text
Grab 300 worth of VTI in the brokerage account now, and after that move 300
from checking into brokerage so the cash is restored.
```

With balances `{"checking": 300, "brokerage": 0}`, allowed destination
`brokerage`, and allowed actions `buy, transfer`, expected normalized actions
are:

```json
{
  "actions": [
    {"action": "buy", "amount": 300, "from": "brokerage", "to": "brokerage"},
    {"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"}
  ]
}
```

Expected findings:

- Python: `negative_source_balance` on action 1
- TLC: failed invariant with `violations = {"negative_source_balance"}` in the
  output trace

## Current Limits

This is a demo extractor, not a finance agent. The local model is intentionally
small, and some ambiguous text will still produce imperfect JSON or odd account
labels. That is acceptable for this milestone as long as the UI makes the
failure visible. A structured extraction failure means policy/TLC checks are
skipped and the response is blocked.

The deterministic layer only normalizes narrow, safe variants such as
`brokerage account` -> `brokerage` and `send` -> `transfer`. It does not invent
missing amounts, accounts, or destinations.
