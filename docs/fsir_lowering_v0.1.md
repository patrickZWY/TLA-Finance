# FSIR v0.1 bounded TLA+ lowering

`safety.fsir_lowering` is the deterministic backend for the approved FSIR v0.1
validation/migration boundary. It emits direct TLA+, a TLC configuration, a
source map, and a hash manifest. Unsupported input is rejected before any
artifact is emitted.

## Supported subset

- concrete or explicitly bounded initial state for money, asset-notional,
  integer, Boolean, and enum variables;
- closed guards and `set`/`add`/`sub` updates;
- legacy atomic, submit, environment-outcome, and conditional-outcome actions;
- fixed sequences, mutually exclusive plans, and bounded partial orders;
- state/action constraints, invariants, precedence traces, and eventual
  liveness properties;
- weak and strong action fairness assumptions without attached formulas.

The partial-order form is the concurrency primitive for the transfer-settlement
slice. Actions execute at most once. Control edges are prerequisites, while
actions without a cross-edge can interleave.

Finance-policy properties apply to the economic actions named by the legacy
compatibility map. Additional lifecycle actions may update status/control
state, but the lowerer rejects any unmapped lifecycle action that writes money
or asset state; this prevents lifecycle expansion from bypassing the canonical
finance policy.

The lowerer rejects blocking unresolved items, ambiguous or parallel control,
retry/time-horizon semantics, unsupported assumption kinds, formulas attached
to fairness assumptions, temporal expressions in guards or updates, duplicate
update targets, action/outcome event-ID collisions, and any expression outside
the closed FSIR AST. This boundary is intentional; it is not a general TLA+
compiler.

## Stable identity and evidence

Generated state, action/outcome, and property identifiers combine a readable
FSIR-derived slug with the first eight hexadecimal characters of the SHA-256 of
the complete stable FSIR ID. Branch tokens use a 12-character digest. The
source map retains the exact FSIR IDs and source-span IDs. Emitted fairness
clauses are named by stable assumption operators and mapped to their FSIR
assumption IDs, action IDs, kinds, and provenance spans.

The manifest records SHA-256 values for:

- canonical FSIR JSON, original source document, and canonical policy snapshot;
- emitted TLA+ model, TLC config, and canonical source map;
- the lowerer source file and, when supplied, the exact `tla2tools.jar`.

`verify_lowered_fsir` regenerates the complete artifact set and fails if the
model, config, source map, or manifest differs. `normalize_tlc_counterexample`
maps TLC state blocks back to a sequence of:

```json
{
  "step": 1,
  "event_id": "event.buy.execute",
  "operator_id": "Act_event_buy_execute_...",
  "before": {"state.cash.brokerage": 0},
  "after": {"state.cash.brokerage": -300}
}
```

Only observable FSIR state is included. Normalization rejects duplicate or
unknown event mappings, repeated one-shot events, missing `lastEvent`, and
missing observable values.

TLC results are classified as exactly `passed`, `property_violation`,
`temporal_violation`, or `infrastructure_failure`. A recognized violation must
use TLC's violation exit code and map to a known generated property; the
evidence runner additionally requires the expected property ID and a nonempty
strict trace. A module, parser, config, or tool error cannot satisfy an
expected-unsafe oracle.

Each run writes an execution-evidence manifest that SHA-256 binds the lowering
manifest, raw TLC output, normalized trace, exact classification, and per-case
execution report. `verify_execution_evidence` rejects drift in any artifact.

## Reproduce the TLC evidence

From the repository root:

```bash
.venv/bin/python -m scripts.run_fsir_lowering_evidence \
  --tla-tools-jar /path/to/tla2tools.jar \
  --output /tmp/fsir-lowering-evidence
```

The ordered lifecycle must pass. The partial-order lifecycle deliberately lets
the buy execute before transfer settlement and must produce an invariant
counterexample bound to the expected property and a nonempty strict trace. The
report also requires infrastructure failure to remain distinct and model,
config, source-map, property, policy, and manifest mutations to be rejected.

This milestone does not claim support for arbitrary FSIR constructs, unbounded
models, refinement proofs, or proof evidence beyond the emitted bounded TLC
configurations.
