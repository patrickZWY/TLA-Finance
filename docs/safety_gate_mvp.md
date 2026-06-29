# Finance Safety Gate MVP

The safety gate is an independent agent that checks concrete finance actions before a finance agent can perform them.

## Agent interface

The workflow is packaged as `TlaSafetyAgent`:

```python
from safety.agent import TlaSafetyAgent

agent = TlaSafetyAgent(artifact_root="artifacts/safety-runs")
result = agent.check(
    finance_agent_output='{"actions":[{"action":"transfer","amount":500,"from":"checking","to":"brokerage"}]}',
    policy={
        "budget": 1000,
        "account_balances": {"checking": 1200, "brokerage": 0},
        "allowed_destination_accounts": ["brokerage"],
    },
    run_name="api-run-001",
)

if result.requires_user_decision:
    # Surface result.findings and result.artifact_dir to the user.
    # Call again with user_decision="stop" or user_decision="continue".
    pass
```

For simple API integrations, `agents.tla_safety_agent.run(...)` returns a
JSON-serializable report dict. The web API uses the OpenAI semantic transformer
for normal local runs so prose such as "move $500 from checking into brokerage"
or "purchase $200 of VTI from brokerage" is normalized before TLA generation.
Pass `structured_json=True` when feeding it fixture-style action JSON.

By default the low-level safety agent expects already-structured JSON. For
deterministic tests and fixtures, the app still supports fenced action blocks:

````markdown
```finance-actions
{"actions":[{"action":"transfer","amount":500,"from":"checking","to":"brokerage"}]}
```
````

For soft recommendations with no executable action:

````markdown
```finance-actions
{"actions":[]}
```
````

The API safety gate no longer depends on this block in normal local runs. It
uses an LLM transformer to read the user request plus finance-agent response
and emit the canonical action schema. That avoids false warnings when the
finance-agent wording is semantically clear but the message format is imperfect.
Set `SAFETY_ACTION_TRANSFORMER=block` to force deterministic block parsing for
fixture tests.

```python
from safety.agent import TlaSafetyAgent
from safety.transformer import FinanceActionsBlockTransformer

agent = TlaSafetyAgent(transformer=FinanceActionsBlockTransformer())
```

## V1 flow

1. The finance agent proposes actions.
2. A semantic transformer converts the proposal into normalized JSON:

```json
{
  "actions": [
    {
      "action": "transfer",
      "amount": 500,
      "from": "checking",
      "to": "brokerage"
    }
  ]
}
```

3. The user policy supplies budget, account balances, and allowed destination accounts.
4. The safety gate writes organized artifacts:
   - normalized action JSON
   - normalized policy JSON
   - readable PlusCal/TLA+ module
   - TLC config
   - PlusCal translator output
   - TLC output
   - report JSON
5. The CLI runs the PlusCal translator with `pcal.trans -nocfg`.
6. TLC checks the translated model and invariants.
7. If there is a violation, the user sees an explanation and chooses whether to stop or continue.

## Chat integration

The FastAPI `/api/chat` route now consults the TLA safety agent before returning
a finance-agent response to the UI. If the safety gate finds a violation, the
API stores the original finance response in `session_data.pending_safety_review`
and returns a warning report instead. The user can then reply:

- `continue` to record a false-positive override and show the original response
- `stop` to terminate the proposed plan

No separate frontend endpoint is required; the existing chat state round-trips
the pending review through `session_data`.

For demos and regression checks, `/api/demo/bad-suggestion` injects one of the
known bad finance-agent fixture replies through the same safety gate. The UI
exposes this as **Demo bad warning**. The endpoint also applies the matching
fixture policy so a fresh browser session can reproduce a warning without
manually configuring accounts first.

The safety checker reads `session_data.safety_policy` when present:

```json
{
  "safety_policy": {
    "budget": 1000,
    "max_individual_action_amount": 400,
    "account_balances": {
      "checking": 1200,
      "brokerage": 0
    },
    "allowed_destination_accounts": ["brokerage"]
  }
}
```

If no policy is configured, concrete executable actions fail closed with a
warning. Soft recommendations with no executable action can pass.

In the local web UI, use the **Safety policy** button in the header to set this
policy. It is stored with the browser session data and sent to `/api/chat` on
each request.

By default, local safety artifacts are written to `artifacts/safety-runs`. Set
`SAFETY_ARTIFACT_ROOT` to override this. Set `SAFETY_RUN_TLC=0` to skip
PlusCal/TLC execution during local UI smoke tests.

The generated TLA follows the same workflow style as the local reference model
at `../Platypus-Model/tla-model/2-stage-platypus-v7`: keep the transition
logic in C-style PlusCal, translate it into TLA with the official PlusCal
translator, then model-check the translated module with TLC.

## V1 invariants

- Action type must be approved.
- Amount must be positive.
- Destination account must be user-approved.
- Total planned outflow must not exceed the user budget.
- No individual action can exceed `max_individual_action_amount`.
- Debit actions must not make source balances negative.
- Debit actions must use source accounts present in `account_balances`.
- Destination accounts are credited when the destination exists in
  `account_balances`, so action order matters. A transfer can fund a later buy;
  a buy before the funding transfer fails.

For v1, the account allowlist is enforced on `to` destinations. Source accounts are checked for existence and non-negative balances.

## Run with simulated finance-agent output

Safe fixture:

```sh
python3 -m safety.cli check \
  --actions fixtures/actions.safe.json \
  --policy fixtures/policy.dev.json \
  --run-name safe-demo \
  --auto-decision stop
```

Destination violation:

```sh
python3 -m safety.cli check \
  --actions fixtures/actions.destination_violation.json \
  --policy fixtures/policy.dev.json \
  --run-name destination-violation-demo \
  --auto-decision stop
```

Budget violation:

```sh
python3 -m safety.cli check \
  --actions fixtures/actions.budget_violation.json \
  --policy fixtures/policy.dev.json \
  --run-name budget-violation-demo \
  --auto-decision stop
```

During development, add `--skip-tlc` to generate artifacts without requiring local TLA+ tools. Without `--skip-tlc`, the CLI fails closed if TLC is not configured and asks the user for a decision.

For markdown output from the current finance agent, use:

```sh
python3 -m safety.cli check \
  --actions fixtures/finance_reply.benign.safe_actions.md \
  --policy fixtures/policy.dev.json \
  --transformer block
```

Benign fixtures:

- `fixtures/finance_reply.benign.empty.md`
- `fixtures/finance_reply.benign.safe_actions.md`

Bad fixtures:

- `fixtures/finance_reply.bad_destination.md`
- `fixtures/finance_reply.bad_budget.md`
- `fixtures/finance_reply.bad_balance.md`

Complex policy:

- `fixtures/policy.complex_budget700_item400.json`
- `fixtures/policy.flow_budget600_item300.json`

Complex benign fixtures:

- `fixtures/finance_reply.complex_benign.multi_action.md`
- `fixtures/finance_reply.complex_benign.edge_budget.md`
- `fixtures/finance_reply.flow_benign.transfer_then_buy.md`: starts with zero
  brokerage balance, transfers funds in, then uses that credited destination in
  a later action.

Complex bad fixtures:

- `fixtures/finance_reply.complex_bad.cumulative_budget.md`: all individual actions are under 400, but total outflow is 701 against a 700 budget.
- `fixtures/finance_reply.complex_bad.individual_item.md`: total outflow is under 700, but one action is 401 against a 400 per-action cap.
- `fixtures/finance_reply.complex_bad.combined_budget_and_item.md`: the 300 + 401 example; it violates both total budget and per-action cap.
- `fixtures/finance_reply.complex_bad.destination_and_budget.md`: mixes allowed destinations with an unauthorized destination.
- `fixtures/finance_reply.complex_bad.balance.md`: stays under budget but overdraws the source account.
- `fixtures/finance_reply.flow_bad.buy_before_transfer.md`: contains the same
  amounts as the benign flow case but in an unsafe order.

Natural-language semantic cases:

- `fixtures/semantic_codex_cases.json`: prose-only user/agent examples paired
  with Codex-generated canonical action JSON. These cover safe multi-action
  plans, cumulative budget violations, unsafe order, and mixed destination plus
  budget violations. See `docs/local_semantic_testing.md` for the local prompt
  and workflow.

TLC reports the first invariant failure it encounters for a run. The Python
policy mirror lists all immediate findings so the user warning can explain
multiple violations at once.

When TLC is enabled, the `.tla` file in the artifact directory is rewritten by
`pcal.trans` and should contain a `BEGIN TRANSLATION` block before TLC runs.
