# Finance Specification IR (FSIR) v0.1

FSIR is the typed, reviewable boundary between prose interpretation and
deterministic formal-model lowering:

```text
prose
  -> candidate FSIR
  -> deterministic validation + unresolved questions
  -> human approval
  -> deterministic TLA+/PlusCal lowering
  -> property-specific TLC evidence
```

Pydantic validates shape, referential integrity, recursive expression types,
effect types, exact dependency metadata, compatibility semantics, and
model-relative bounds. It is not the proof system. TLA+/TLC remains responsible
for exploring modeled behaviors and checking safety/liveness properties.

## Closed contract

`safety/fsir.py` defines every accepted field and rejects extras at every
layer. Expressions use a closed typed AST; FSIR cannot contain arbitrary
Python, TLA+, SMT, or other backend snippets.
Pydantic 2.x is pinned as the schema-generation major version so the
checked-in JSON Schema is reproducible across development environments.

An FSIR document contains:

- `meta`: version, real source digest, domain profile, intent classification,
  currency, budget meaning, and creation tool;
- `policy`: a canonical, provenance-bound finance-policy snapshot containing
  budget, per-action cap, configured initial cash, allowed destinations and
  action kinds, and gross-debit semantics;
- `symbols`: declared actors/services, cash accounts, instruments, and asset
  positions;
- `state`: typed initial variables, or an explicit bounded nondeterministic
  initial domain, with symbol and source-span links;
- `actions`: stable IDs, actor, typed parameters, guards, reads/writes,
  atomic updates or conditional outcomes;
- `control`: none, sequence, choice, parallel, partial order, or unresolved
  ambiguous control;
- `properties`: named invariants, action constraints, trace properties, and
  liveness properties;
- `assumptions`: environment, fairness, timing, and trusted-fact assumptions;
- `bounds`: finite action/step/retry/time and domain bounds;
- `unresolved`: blocking or warning questions with affected stable IDs;
- `provenance`: exact source spans and derivation method;
- `compatibility`: the typed legacy action/choice payload plus a complete
  legacy-path-to-FSIR-ID map.

The checked-in generated schema is
`docs/fsir-v0.1.schema.json`.

## Deterministic validation

Cross-reference validation rejects:

- duplicate stable IDs;
- source or policy digests that do not match their exact provenance content;
- undeclared action actors;
- unknown state/symbol/action/property/span references;
- untyped or malformed expression shapes;
- non-Boolean guards/properties and ill-typed expression operands/effects;
- non-exact action read/write dependencies or action/step bounds;
- conditional actions without explicit outcomes;
- invalid or non-canonical control nodes/edges/branches;
- incomplete, forged, or semantically drifting legacy compatibility maps;
- unsupported legacy action kinds and duplicate lowering identities;
- placeholder/non-SHA-256 source digests.

Budget semantics are mandatory. The current compatibility migration records
`gross_debit`, matching the existing policy mirror's counter. The canonical
policy snapshot is the single trusted source from which validation derives the
mandatory, exact executable property set; deleting, weakening, or relabelling
one of those properties fails validation. The adapter emits typed constraints
for gross-debit budget,
per-action amount, positive amount, allowed destination, allowed action kind,
and known debit-source checks. `Property.finding_code` uses a closed vocabulary
and is bound to each canonical formula. A future net spend or external-outflow
policy must use a different explicit value and formula.

Every declared cash account has exactly one money state. Configured policy
accounts must use the exact concrete initial balance from
`policy.initial_cash_by_account_id` and cite the canonical policy span;
unconfigured accounts must instead use an explicit bounded nondeterministic
initial domain. The policy ID is derived canonically from the FSIR document ID.
This prevents the trusted policy and the formal initial state from drifting.

## No action versus underspecified action

An empty legacy action list no longer has one ambiguous meaning:

- `no_action`: no executable intent, no actions, and no blocking unresolved
  questions;
- `underspecified_action`: intended work is blocked by at least one explicit
  unresolved question, such as a missing dollar amount.

The validator rejects `underspecified_action` without a blocking question and
rejects `no_action` with one. This keeps “educational advice only” distinct
from “the user intended a transfer but omitted the amount.”

## Cash and asset positions

The legacy adapter preserves the original payload byte-for-structure through
typed compatibility models, while its FSIR state/effects separate cash from
asset positions:

```text
buy:
  subtract state.cash.<account>
  add      state.position.<account>.<instrument>
```

A buy never credits the same cash account it debited. When an instrument is
not recoverable from the source text, the adapter creates an explicit
`instrument.unspecified` position plus an unresolved question.

Missing configured initial balances do not silently become concrete values.
They reference a finite `integer_set` bound through
`initial_domain_bound_id`, making the nondeterministic interpretation explicit.
Unsupported action kinds fail validation; lowering-critical swap ambiguity is
blocking.

## Seed migration

The 12 existing semantic cases are checked in at
`fixtures/fsir/semantic_codex_cases.fsir.json`.

Regenerate deterministically:

```bash
python scripts/migrate_semantic_cases_to_fsir.py
python scripts/generate_fsir_schema.py
```

The migrated suite contains 10 action plans, one genuine no-action case, and
one blocking underspecified-action case. Tests reparse every FSIR document and
recover every original action/choice payload exactly. Adversarial regressions
also mutate parameter/expression/domain types, dependencies, bounds,
compatibility paths/effects, identities, choice topology, and action kinds; all
must fail closed. Further regressions remove or weaken the policy property set,
forge source identity, relabel verdict codes, and duplicate dependency entries.

## Current boundary

This foundation does not yet lower general FSIR to TLA+. The current TLA
generator remains the L0 compatibility path. The next lowering milestone
should consume approved FSIR, emit a complete stable-ID source map, and return
per-property checked/pass/fail/not-checked results rather than one generic TLC
status.
