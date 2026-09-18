# TLA-Finance Plan

## Potential Future Direction: Fast Local LLMs With Small Composable Specs

- On a future Apple Silicon Mac, evaluate Uzu as a local inference backend for
  faster chat generation and semantic extraction.
- Keep Uzu behind the existing transformer boundary rather than coupling it to
  the safety checker directly.
- Use faster inference to support more frequent checks over small, composable
  TLA+/PlusCal artifacts instead of generating one large monolithic spec.
- Preserve the current feedback loop:
  natural finance text -> canonical action JSON -> Python policy checks ->
  targeted TLA+/TLC checks -> aggregated findings.
- Benchmark any Uzu path against the current Ollama/OpenAI-compatible path on
  schema validity, action extraction accuracy, safety finding agreement, and
  latency before adopting it.


## Possible Direction: EARS Requirements Before Formalization

The workbench currently extracts normalized actions (and, where applicable,
named action choices) directly from finance advice. A possible future layer is
[EARS (Easy Approach to Requirements Syntax)](https://alistairmavin.com/ears/):
a lightweight, structured natural-language form such as:

```text
While the brokerage balance is zero,
when the user selects "buy first",
the Finance Safety Workbench shall block the action.
```

EARS is **not part of the current execution path**. It could become a
reviewable intermediate representation between free-form advice and the
choices/TLA+ model, especially for preconditions, triggers, exceptions, and
either/or alternatives. The safety decision would remain grounded in the
normalized choice model and TLC results; EARS would make the translation more
auditable rather than replace formal checking.

## Possible Direction: Execution Semantics for Concurrent and Asynchronous Plans

The legacy canonical action list is evaluated as an ordered, immediate
sequence: a transfer credits its destination before a later action is checked.
That is suitable for the prose demo, but it does not represent operational
timing such as asynchronous transfer settlement or independently submitted
orders. (The bounded FSIR path already models partial-order
transfer-settlement lifecycles; see `docs/fsir_lowering_v0.1.md`.)

A future version could have the semantic extractor identify execution
semantics alongside the finance actions. For example, it could distinguish
between an explicitly ordered instruction:

```text
Transfer $300 to brokerage, then wait for it to settle before buying $300 of VTI.
```

and concurrent submission:

```text
Submit a $300 transfer to brokerage and immediately submit a $300 VTI buy.
Do not wait for the transfer to settle.
```

The normalized plan could represent action IDs, settlement dependencies, and a
mode such as `ordered`, `concurrent`, or `ambiguous`. Natural-language cues
such as "then," "after it clears," and "once funds are available" would create
an order dependency; "simultaneously," "submit both," "immediately," and
"without waiting" would permit concurrent execution. A bare "and" should not
silently be treated as a guaranteed order: it could be modeled conservatively
as ambiguous or trigger a request for confirmation.

For explicitly ordered plans, the Python preflight and a sequential TLA+
model would retain today's behavior. For concurrent or ambiguous plans, the
generated TLA+ model could nondeterministically interleave submission and
settlement events. That would let TLC find a counterexample where, for example,
a brokerage buy executes before a pending transfer settles, even though the
same actions pass a Python preflight under the intended serial ordering. This
would make the difference between policy validation and temporal safety
checking visible without introducing an artificial disagreement between them.
