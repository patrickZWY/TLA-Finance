# Local LLM Safety Workbench Design

## Purpose

The workbench demonstrates one specific claim: ambiguous finance language can be
translated by a local LLM into canonical action JSON, then checked by a
deterministic Python policy layer and a TLA+/TLC model checker before execution.

This is not a production finance app and does not execute real financial
transactions. It is a demo harness for semantic extraction and safety checking.

## Goals

- Run without a paid API by using a local OpenAI-compatible model server.
- Let the user choose or write ambiguous finance advice.
- Let the user configure security invariants in the browser.
- Show the exact normalized action JSON produced by the local model.
- Show Python policy findings and optional PlusCal/TLC findings.
- Fail closed when extraction is invalid or incomplete.
- Preserve raw model output when extraction fails so model behavior is debuggable.

## Non-Goals

- No real brokerage, bank, or payment integration.
- No real financial advice.
- No autonomous finance agent is required for the current demo.
- No guarantee that a small local model always extracts correct semantics.
- No hidden repair of missing amounts, accounts, or destinations.

## Architecture

```text
Browser workbench
      |
      | POST /api/semantic-check
      v
FastAPI backend
      |
      v
OpenAIActionTransformer
      |
      | local Ollama qwen3:4b
      v
Canonical actions JSON
      |
      +--> Python policy mirror
      |
      +--> PlusCal/TLC model checker
      |
      v
Structured result for UI
```

## Frontend

The frontend is a single static page at `public/index.html`, served by FastAPI.

It has three main areas:

- Input: pre-populated ambiguous finance messages or custom user text.
- Security invariants: budget, max individual amount, account balances, allowed
  destinations, and allowed action types.
- Result: normalized actions, Python findings, TLC status/output, artifacts,
  usage metadata, and raw model output on extraction failure.

The UI talks only to `/api/semantic-check` for this demo path.

## Backend Endpoint

`POST /api/semantic-check` accepts:

```json
{
  "user_message": "optional user context",
  "finance_advice": "ambiguous finance advice",
  "policy": {
    "budget": 700,
    "max_individual_action_amount": 400,
    "account_balances": {"checking": 1000, "brokerage": 0},
    "allowed_destination_accounts": ["brokerage"],
    "allowed_action_types": ["buy", "transfer"]
  },
  "run_model_checker": true
}
```

The endpoint:

1. Validates the policy.
2. Sends combined user context and finance advice to the semantic transformer.
3. Validates the returned action JSON with `FinanceAction`.
4. Runs the Python policy mirror.
5. Runs `TlaSafetyAgent` with precomputed actions.
6. Returns a structured response for the UI.

If extraction fails, the endpoint returns `decision: "extraction_failed"` and
does not run Python policy or TLC checks.

## Semantic Extraction

`OpenAIActionTransformer` is the semantic boundary. It maps prose into:

```json
{
  "actions": [
    {"action": "transfer", "amount": 350, "from": "checking", "to": "brokerage"}
  ]
}
```

For Ollama on `localhost:11434`, the transformer uses Ollama's native
structured-output `/api/chat` path and sends `think: false`. This is important
for `qwen3:4b`; otherwise the model may spend output tokens in a reasoning
field and return empty or malformed JSON content.

The transformer has narrow deterministic normalization after extraction:

- action synonyms such as `send` -> `transfer`
- account suffixes such as `brokerage account` -> `brokerage`

It does not invent missing required fields. Missing `action`, `amount`, `from`,
or `to` blocks the run.

## Safety Layers

The Python policy mirror catches common violations quickly:

- disallowed action type
- non-positive amount
- disallowed destination
- total budget exceeded
- individual action limit exceeded
- unknown source account
- negative source balance

The PlusCal/TLC layer model-checks the same normalized action sequence against
the generated invariants. This is especially useful for order-sensitive cases,
such as buying from an unfunded account before a later transfer funds it.

## Failure Modes

The demo intentionally keeps failure states visible:

- Invalid local-model JSON: blocked as `extraction_failed`.
- Missing action fields: blocked as `extraction_failed`.
- Odd but complete account labels: normalized only for narrow safe variants.
- Policy violation: blocked with Python and/or TLC findings.
- TLC unavailable or failed: reported in the result instead of hidden.

This keeps the local model accountable for semantic extraction quality.

## Successful Demo Cases

Destination and budget violation:

```text
Send 350 from checking to brokerage, set aside 350 from checking for savings,
and wire 50 from checking to Alex for tickets.
```

Expected result:

- three transfer actions
- `disallowed_destination` for `Alex`
- `budget_exceeded` at total outflow `750` over budget `700`

Order-sensitive balance violation:

```text
Grab 300 worth of VTI in the brokerage account now, and after that move 300
from checking into brokerage so the cash is restored.
```

Expected result:

- buy from brokerage before transfer
- Python catches `negative_source_balance`
- TLC reaches a state with `violations = {"negative_source_balance"}`

## Next Design Steps

- Add mocked endpoint tests for success and extraction-failure responses.
- Add screenshot or short recording documentation for the two successful demos.
- Add optional model selection if comparing local parsers becomes useful.
- Keep any future finance-agent simulation separate from the semantic extractor
  so extraction quality remains testable in isolation.
