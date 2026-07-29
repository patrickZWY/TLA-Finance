# TLA-Finance Phase 3B Corpus v0.2.1

This isolated artifact defines 30 execution-grounded semantic cores for the
agent demo and regression suite. It does not modify the owner repository.
Focused specification and product compatibility rechecks approved the unchanged
v0.2 structure. v0.2.1 refreshes only executable evidence to independently
approved lowering commit `d45efd09ffe5c77b89fcad1954d7959e54b7b8f3`.

The v0.1 review anchor remains the original `phase3b-corpus.tar.gz` with
SHA-256 `b252a59ca7f63924863ed66bdf7ec58a39c97f8e798117c9334ca44e485b4c82`.
This directory is the v0.2.1 evidence-refresh artifact set.

## Files

- `corpus.json`: cases, semantic requirements, product projections, lowering
  expectations, and two exact frozen-backend fixtures.
- `corpus.schema.json`: closed JSON Schema for v0.2.1.
- `validate_corpus.py`: dependency-tolerant semantic/reference/replay gate.
- `backend-evidence.json`: reproduced approved `d45efd0` real-TLC report.
- `mutant-results.json`: all 32 semantic mutant oracles and their honest
  execution status (defined, not yet executed without a corpus materializer).
- `validator-mutation-results.json`: four focused fail-closed mutation results
  for mapping completeness and evidence-digest binding.
- `backend-artifacts/`: raw FSIR input, TLA/CFG/source map, manifests,
  classifications, normalized traces, reports, and TLC output for both exact
  fixtures.
- `case-matrix.md`: reviewer-facing coverage and backend disposition.
- `hero-demo.md`: replayable eight-state demo.
- `review-closure.md`: concise spec/product blocker-to-gate mapping.
- `validation-results.md`: exact final commands, outputs, and mutant scope.
- `revise_v02.jq`: deterministic v0.1→v0.2 migration.
- `refresh_v021.jq`: deterministic evidence-only v0.2→v0.2.1 refresh.
- `enrich.jq`: retained v0.1 build input for review provenance only.

## Two contracts, kept separate

`expected_semantics` is a corpus research projection. Its action labels,
control vocabulary, and scenario bounds state the meaning a future FSIR
materializer must preserve; it is deliberately not represented as a serialized
FSIR v0.1 document.

`lowering_oracle` has a closed disposition:

- `lower` — execute the referenced exact FSIR fixture and require its frozen
  manifest/TLC oracle;
- `reject_blocking` — reject before emitting model, config, source map, or
  manifest because meaning remains blocked;
- `unsupported` — quarantine the case with a deterministic capability reason;
  do not fabricate backend artifacts.

The distribution is 2 lower, 8 reject-blocking, and 20 unsupported. The two
lowerable fixtures are exact documents produced by
`tests.test_fsir_lowering.lifecycle_document` at independently approved commit
`d45efd09ffe5c77b89fcad1954d7959e54b7b8f3` with pinned TLC jar SHA-256
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`:

- sequence → real TLC classification `passed`, normalized counterexample `[]`;
- partial order → real TLC classification `property_violation` on
  `property.safe_transfer_then_buy_order_sensitive.no_negative_cash`,
  normalized events `event.buy.submit`, `event.buy.execute`.

Each fixture records the actual lowering and execution-evidence manifest hashes
and source-map direction: states are keyed by FSIR state ID, while operators/
properties/branches are keyed by generated TLA names whose values carry exact
FSIR IDs.

## Product/evidence contract

Each case supplies stable source, node, property, finding, trace, approval, and
counterexample references. Failing paths begin with a nonviolating Init state,
then follow `negative_traces[0].semantic_event_ids` exactly. The first violating
state exists in the path, earlier states have no violation, the failing finding
points to the final transition, and each financial state has cash balances.

Every product state has a closed control envelope. Only
`bounded_approval_required` enables approval; unavailable enables rerun/edit/
stop; violation enables revise/inspect/stop; stopped enables resume/new-goal
and no tool action. Inconclusive/unavailable evidence includes a closed reason.

The hero stages contain full projection snapshots: version/review/evidence
status, fixture-linked counterexample, v0→v1 revision, stale-v0 invalidation,
fresh v1 model hash, a preserved property/assumption/bounds contract hash,
state-specific controls, activity event, and stage-8 approval scope.

The corpus defines the required state/control contract; it does not claim the
current frontend enforces it. Phase 3C must still gate rendered controls by
state and treat a valid zero-action plan as `checks_passed`.

The 30 case/oracle structure is unchanged from frozen v0.2. Its canonical case
fingerprint excluding only the refreshed `lowering_oracle.frozen_commit` field
is `d5745e96cab0c94a0388ed9e5d39c6a9a7308a54e2c931a0d333e76d274fb793`.

## Validation

Run:

```bash
python3 validate_corpus.py
```

If `jsonschema` is installed, the closed schema gate runs first. If it is not
installed (as in the frozen Phase 3A environment), all dependency-free semantic
and cross-reference gates still run and report that only the schema library
gate was skipped.

The validator checks:

1. exactly 30 ordered cores and two exact backend fixtures;
2. source/property/node/state/action/approval references;
3. lower/reject/unsupported artifact rules;
4. exact frozen fixture bounds, manifests, normalized event IDs, and source-map
   direction;
5. state→control permissions and structured unavailable reasons;
6. counterexample action order, balances, and earliest-violation semantics;
7. the eight hero states, stale-evidence invalidation, fresh hash, preserved
   contract hash, and bounded approval.
