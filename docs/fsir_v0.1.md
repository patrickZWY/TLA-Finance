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

Pydantic validates the shape and referential integrity of the model. It is not
the proof system. TLA+/TLC remains responsible for exploring modeled behaviors
and checking safety/liveness properties.

## Closed contract

`safety/fsir.py` defines every accepted field and rejects extras at every
layer. Expressions use a closed typed AST; FSIR cannot contain arbitrary
Python, TLA+, SMT, or other backend snippets.
Pydantic 2.x is pinned as the schema-generation major version so the
checked-in JSON Schema is reproducible across development environments.

An FSIR document contains:

- `meta`: version, real source digest, domain profile, intent classification,
  currency, budget meaning, and creation tool;
- `symbols`: declared actors/services, cash accounts, instruments, and asset
  positions;
- `state`: typed initial variables with symbol and source-span links;
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
- undeclared action actors;
- unknown state/symbol/action/property/span references;
- untyped or malformed expression shapes;
- conditional actions without explicit outcomes;
- invalid control nodes/edges/branches;
- incomplete legacy-to-FSIR ID maps;
- placeholder/non-SHA-256 source digests.

Budget semantics are mandatory. The current compatibility migration records
`gross_debit`, matching the existing policy mirror's counter. A future net
spend or external-outflow policy must use a different explicit value.

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
recover every original action/choice payload exactly.

## Current boundary

This foundation does not yet lower general FSIR to TLA+. The current TLA
generator remains the L0 compatibility path. The next lowering milestone
should consume approved FSIR, emit a complete stable-ID source map, and return
per-property checked/pass/fail/not-checked results rather than one generic TLC
status.
