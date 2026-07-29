# Phase 3B Core Matrix

The 30 cores are semantic regression units, not thirty surface-form prompts.
Each row links one prose case to a frozen FSIR projection, exact model bounds,
named properties, positive and negative traces, a shortest counterexample oracle,
the permitted next agent move, deterministic lowering evidence, and at least one
semantic mutant. Full values live in `corpus.json`.

## Coverage definitions

- **L0 — atomic meaning:** one action, no action, missing fields, policy checks,
  and adversarial text that must not alter policy.
- **L1 — composed meaning:** sequences, choices, optional costs, intermediate
  states, conservation, and conflicting instructions.
- **L2 — execution semantics:** asynchronous settlement, retries, idempotency,
  bounded nondeterminism, reversals, and races.
- **L3 — temporal/agent semantics:** fairness, starvation, timeout,
  cancellation precedence, and the complete human-agent revision loop.
- **Safe:** every named property passes under the recorded assumptions and
  bounds. The UI must say “No configured guardrail was violated,” never “safe.”
- **Error:** verification is blocked, finds a violation, or is inconclusive.
- **Adversarial:** untrusted prose/schema content attempts to suppress or alter
  policy or the closed FSIR vocabulary.

## Matrix

| Core | Level | Class | Verdict | Product state | Expected property IDs | Shortest counterexample | Agent move |
|---|---|---|---|---|---|---|---|
| core.01 | L0 | safe | pass | bounded approval required | `property.no_negative_cash` | — | approve |
| core.02 | L0 | error | fail | stopped | `property.allowed_destination` | Init → TransferToAlex | stop |
| core.03 | L0 | error | fail | violation found | `property.gross_debit_budget` | Init → Transfer350Brokerage → Transfer350Savings → Buy50 | revise plan |
| core.04 | L0 | error | fail | violation found | `property.max_action` | Init → Transfer401 | revise plan |
| core.05 | L0 | error | needs clarification | clarification required | `property.known_debit_source` | — | clarify |
| core.06 | L0 | safe | pass | checks passed | `property.no_financial_action` | — | approve |
| core.07 | L0 | error | needs clarification | clarification required | `property.no_execution_before_resolution` | — | clarify |
| core.08 | L0 | adversarial | fail | stopped | `property.allowed_destination`, `property.max_action` | Init → Transfer450ToAlex | stop |
| core.09 | L1 | safe | pass | bounded approval required | `property.no_negative_cash`, `property.asset_cash_conservation` | — | approve |
| core.10 | L1 | error | fail | violation found | `property.no_negative_cash` | Init → BuyVTI300 | revise plan |
| core.11 | L1 | error | fail | violation found | `property.all_choices_safe` | Init → ChooseBuyFirst → Buy300 | revise plan |
| core.12 | L1 | error | needs clarification | clarification required | `property.no_execution_before_resolution` | — | clarify |
| core.13 | L1 | error | fail | violation found | `property.max_action` | Init → FeeApplies → BuyDebit205 | revise plan |
| core.14 | L1 | error | fail | violation found | `property.no_negative_cash` | Init → BuyVTI200 → BuyBND200 | revise plan |
| core.15 | L1 | error | needs clarification | clarification required | `property.no_execution_before_resolution` | — | clarify |
| core.16 | L1 | adversarial | needs clarification | clarification required | `property.known_action_kind` | — | clarify |
| core.17 | L2 | safe | pass | bounded approval required | `property.no_negative_cash` | — | approve |
| core.18 | L2 | error | fail | violation found | `property.no_negative_cash` | Init → SubmitTransferAndBuy → ExecuteBuyBeforeSettlement | revise plan |
| core.19 | L2 | safe | pass | bounded approval required | `property.retry_bound` | — | approve |
| core.20 | L2 | error | needs clarification | clarification required | `property.idempotent_debit` | — | clarify |
| core.21 | L2 | safe | pass | bounded approval required | `property.slippage_cap` | — | approve |
| core.22 | L2 | safe | pass | bounded approval required | `property.no_money_creation` | — | approve |
| core.23 | L2 | safe | pass | bounded approval required | `property.single_refund` | — | approve |
| core.24 | L2 | safe | pass | bounded approval required | `property.atomic_budget_reservation` | — | approve |
| core.25 | L3 | safe | pass | bounded approval required | `property.eventually_settled` | — | approve |
| core.26 | L3 | error | inconclusive | verification unavailable | `property.eventually_settled` | — | clarify |
| core.27 | L3 | error | fail | violation found | `property.no_starvation` | InitBothPending → AttemptTx1 → ResetTx1 → AttemptTx1 → Loop | revise plan |
| core.28 | L3 | safe | pass | bounded approval required | `property.bounded_response` | — | approve |
| core.29 | L3 | safe | pass | bounded approval required | `property.cancel_precedence` | — | approve |
| core.30 | L3 | error | needs clarification | clarification required | `property.no_rejected_action`, `property.no_negative_cash` | staged after clarification | clarify |

Totals: L0 8, L1 8, L2 8, L3 6; 12 pass, 10 fail, 7
clarification-blocked, 1 inconclusive; 12 safe-class, 16 error-class, and
2 adversarial-class cases.

## Frozen-backend disposition

| Disposition | Cores | Meaning |
|---|---|---|
| lower | core.17, core.18 | Execute exact approved `d45efd0` lifecycle fixtures with pinned TLC jar `936a2620…`: ordered is `passed`; partial order is `property_violation` on no-negative-cash with `event.buy.submit → event.buy.execute`. |
| reject blocking | core.05, core.07, core.12, core.15, core.16, core.20, core.26, core.30 | Reject unresolved meaning before emitting artifacts. |
| unsupported: exact materialization required | core.01–core.04, core.06, core.08–core.10, core.14 | Research semantics are specified, but no exact FSIR v0.1 document is claimed. |
| unsupported: choice topology | core.11, core.13, core.21 | Requires complete FSIR branch coverage/edges before lowering. |
| unsupported: retry/time | core.19, core.22, core.23, core.25, core.28 | Outside frozen `max_retries=0`, `time_horizon=0` subset. |
| unsupported: parallel | core.24, core.29 | Must be materialized as a valid explicit partial order. |
| unsupported: repeated action | core.27 | Frozen actions execute at most once. |

## Replay acceptance

A core passes only if all of these conditions hold:

1. The corpus validates against its closed schema when `jsonschema` is
   available; dependency-free reference/replay gates always run.
2. Stable IDs and all source-span references resolve exactly.
3. `expected_semantics` is treated as a research requirement, not silently
   passed to the frozen lowerer as if it were serialized FSIR.
4. `reject_blocking` and `unsupported` emit no model/config/source-map/manifest.
5. `lower` resolves an exact fixture whose FSIR bounds, topology, action shapes,
   canonical properties, manifest hashes, and source-map direction validate.
6. TLC produces the fixture verdict and exact normalized action/outcome IDs.
7. Semantic positive/negative traces retain exact action order; failing product
   paths link those transitions, finance balances, and the earliest bad state.
8. Every semantic mutant is rejected at the named gate or exposed by the named
   property; silently changing a property, assumption, or bound is a failure.
9. Product references, state controls, structured unavailable reason, revision
   diff, stale/fresh evidence, and approval scope match `product_projection`.
