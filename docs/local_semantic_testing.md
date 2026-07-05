# Local Semantic Action Testing

Use this workflow when you want to test natural finance language without making
a live OpenAI API call. Codex generates the expected canonical action JSON, and
the unit test feeds that JSON through the same safety gate used by the app.

## Codex Prompt

```text
Read the user request and finance-agent response below. Extract only concrete
finance actions that move, spend, invest, withdraw, deposit, buy, sell, or swap
money.

Output only JSON in this exact shape:
{"actions":[{"action":"buy|sell|swap|deposit|transfer|withdraw","amount":123,"from":"account","to":"account"}]}

Rules:
- Treat natural wording semantically. Examples: purchase -> buy, move/send/wire
  -> transfer, liquidate/cash out -> sell, rebalance/exchange -> swap, add cash
  -> deposit, pull cash out -> withdraw.
- Include multiple actions when the statement implies a sequence.
- Preserve order, because account balances can depend on earlier actions.
- Use integer dollar amounts.
- If a concrete action lacks an amount, source, or destination, omit it.
- Do not extract education, comparisons, projections, or hypothetical examples.
- If there are no concrete executable actions, return {"actions":[]}.
```

## Fixture Format

Add cases to `fixtures/semantic_codex_cases.json`:

- `user_request`: natural language from the user.
- `finance_agent_response`: natural language from the finance agent.
- `codex_generated_actions`: the JSON produced by the prompt above.
- `policy`: the policy fixture to check against.
- `expected_finding_codes`: safety findings expected after validation.
- `category`: broad reviewer grouping, such as `safe`, `unsafe`, or
  `adversarial`.
- `risk_type`: the specific behavior being tested.
- `expected_behavior`: short explanation of what the extractor should do.

The test intentionally rejects fenced `finance-actions` blocks in these cases.
The point is to exercise natural prose and then test the downstream safety
invariants over the generated canonical actions.

Run:

```sh
SAFETY_RUN_TLC=0 python3 -m unittest tests.test_semantic_codex_cases
```
