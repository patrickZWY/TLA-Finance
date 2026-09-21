# System Pipeline

TLA-Finance contains two entry points. The browser workbench is the primary demo. The older finance-assistant chat remains available, but it feeds the same safety core after its specialist agents produce a reply.

## Primary demo

```text
public/index.html + styles.css + app.js
              |
              | POST /api/semantic-check
              v
api/index.py
  1. Enforce host, rate, and request-size limits
  2. Validate the submitted SafetyPolicy
  3. Route the branching benchmark directly to its nondeterministic TLA model,
     or continue with action normalization
              |
              v
safety/transformer.py · OpenAIActionTransformer
  4. Normalize prose with an OpenAI-compatible model, or load explicit
     normalized_actions for a deterministic stress case
  5. Parse canonical FinanceAction objects
  6. Reject unsupported amounts, malformed accounts, or invalid choice shapes
              |
              v
safety/validator.py · evaluate_policy
  7. Optionally apply the policy deterministically and in action order
              |
              v
safety/agent.py · TlaSafetyAgent
  8. Generate run inputs and a finite PlusCal/TLA+ model
  9. Optionally translate PlusCal and run TLC
  10. Persist local artifacts and combine all findings into one decision
              |
              v
Sanitized API response
  11. Show one verdict, the normalized actions or decision model, findings,
      state counts, and stage statuses
```

The semantic model is used only for translation from prose to structured actions. It does not decide whether a plan is safe. The deterministic validator and optional model checker operate on the normalized actions. The 100-action benchmark supplies those actions directly so it tests long-sequence verification rather than an LLM's output-length limit.

The branching benchmark is TLC-only. It makes four nondeterministic choices at
each of eight rounds, retaining choice history so all 65,536 decision histories
remain distinct. The Python sequence validator is intentionally disabled
because there is no single input sequence to evaluate.

## Data contracts

The browser submits:

```json
{
  "user_message": "optional context",
  "finance_advice": "move 300 from checking to brokerage",
  "normalized_actions": null,
  "policy": {
    "budget": 600,
    "max_individual_action_amount": 300,
    "account_balances": {"checking": 300, "brokerage": 0},
    "allowed_destination_accounts": ["brokerage"],
    "allowed_action_types": ["buy", "transfer"]
  },
  "run_model_checker": true
}
```

`normalized_actions` is optional. When present, it must use the canonical action schema below and bypasses semantic extraction; all policy and model-checking stages remain unchanged.

The transformer produces either one ordered action list:

```json
{"actions": [{"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"}]}
```

or named, mutually exclusive choices:

```json
{"choices": [{"name": "fund first", "actions": [{"action": "transfer", "amount": 300, "from": "checking", "to": "brokerage"}]}]}
```

The response exposes the decision, normalized plan, findings, public PlusCal/TLC statuses, transformer usage, and timing. Local commands, tool output, and artifact paths remain on the server.

## Decision rules

- Invalid extraction fails closed. Policy and TLC do not run without valid canonical actions.
- The demo can run Python checks, TLC, or both; at least one checker must be enabled.
- A plan is safe only when no findings are present.
- Python checks apply actions in order, including balance credits from earlier transfers.
- If TLC is requested but cannot be configured or completed, the run is blocked with a setup or execution finding.
- Skipping TLC is explicit. In that mode, the deterministic Python policy result controls the demo decision.
- Choice proposals are checked branch by branch; one unsafe branch blocks the overall proposal.

## Policy invariants

For each ordered plan or choice branch, the system checks:

- action kind is allowed;
- amount is positive and no greater than the per-action cap;
- destination is allowed;
- cumulative debit outflow stays within budget;
- debit source exists;
- source balances never become negative as actions are applied.

## Artifacts

Each completed safety run writes a directory below `artifacts/safety-runs/` containing the source text, normalized actions, policy, generated `.tla` and `.cfg` files, checker output when enabled, and `report.json`. The browser only receives `{"generated": true}` so local paths and subprocess details are not exposed.

## Legacy chat path

```text
POST /api/chat or main.py
  -> LLM router
  -> budget / goal / investment / debt specialist
  -> synthesized finance reply
  -> TlaSafetyAgent
  -> pass, or store a pending stop/continue decision
```

Code under `agents/` belongs to this legacy assistant path. It is intentionally separate from the primary workbench, which calls `/api/semantic-check` directly and does not need routing or specialist agents.

## Repository map

```text
api/          HTTP boundary, validation, rate limits, demo and legacy routes
public/       Small static workbench: structure, styling, and behavior
safety/       Canonical models, extraction, policy evaluation, TLA generation, TLC runner
agents/       Legacy specialist-agent and session-storage implementation
fixtures/     Deterministic actions, policies, prose, and semantic evaluation cases
tests/        Behavioral coverage for the API, safety core, configuration, and evaluation tools
scripts/      Local server and repeatable evaluation entry points
docs/         Architecture, setup, deployment, evaluation, and research notes
```
