# Phase 3B v0.2.1 Review-Closure Map

This maps every Phase 3E corpus compatibility blocker to the frozen v0.2
structure and v0.2.1 evidence refresh. The two packaged fixtures and evidence
are regenerated from independently approved bounded lowering commit
`d45efd09ffe5c77b89fcad1954d7959e54b7b8f3` and pinned TLC jar SHA-256
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`.

Final focused verdicts: Product projection **APPROVED** after the core.06
control repair; specification/two-fixture compatibility **APPROVED** after
exact mapping coverage and raw-artifact hash binding. These approvals do not
cover frontend enforcement, the 32 unexecuted semantic mutants, general
lowering beyond the approved bounded subset, or final system integration.

## Specification/lowering review

| Prior blocker | v0.2/v0.2.1 closure | Enforced by |
|---|---|---|
| Unsupported `parallel`/`unresolved` treated as lowerable | Closed `lower`, `reject_blocking`, `unsupported` disposition. Parallel and unresolved cases emit no artifacts unless represented by an exact fixture. | Schema conditional and `validate_case` artifact rules |
| Retry/time semantics treated as supported | Nonzero retry/time cores are quarantined with `unsupported_retry_or_time_semantics`. | Disposition table and no-artifact gate |
| Repeated actions incompatible with at-most-once execution | core.27 is `unsupported_repeated_action_semantics`. | Closed reason enum and no-artifact gate |
| Invalid/incomplete choice topology | Choice cores are `unsupported_choice_topology` until exact branch materialization exists. | Closed reason enum and no-artifact gate |
| FSIR bounds drift | Only exact fixture FSIR documents are lowerable; validator requires `max_actions=max_steps=len(actions)`, `max_retries=0`, `time_horizon=0`. | `validate_fixture` |
| Corpus actions/properties were not FSIR v0.1 shapes | Renamed to `expected_semantics`; executable claims reference embedded exact FSIR documents and explicit semantic→backend action/property maps. | Schema separation and mapping reference gates |
| Blocking cases expected artifacts | Eight blocking cases use `reject_blocking`, `emits_artifacts=false`, no fixture, and a deterministic rejection oracle. | Schema conditional and validator |
| Outcome IDs/source-map direction missing | Exact fixtures permit action/outcome event IDs; source-map direction is explicit for all four maps. | Fixture schema and `validate_fixture` |
| Binary TLC failure classification/weak evidence binding | Approved `d45efd0` evidence is recorded with exact classifications, property IDs, normalized events, lowering manifest, execution-evidence manifest, and pinned tool hash. | Embedded fixtures, `backend-evidence.json`, digest/property/event/tool gates |

## Product review

| Prior blocker | v0.2 closure | Enforced by |
|---|---|---|
| B1 broken counterexample links/balances | Each fail path starts with nonviolating Init, follows the negative semantic event order, links the actual transition, carries cash snapshots, and points `first_violating_state` to the first in-path violation. | Counterexample order/reference/balance/earliest-state gates |
| B2 missing UI reference validation | Questions/nodes resolve source spans; findings resolve property/node/state; approval resolves nodes; counterexample properties/actions resolve and preserve order. | `validate_case` product reference gates |
| B3 unstructured unavailable reason | `verification.reason_code` is closed; core.26 uses `missing_assumption` plus a human-safe message. | Schema and unavailable-reason gate |
| B4 controls not machine-readable | Every projection has a closed 11-boolean control envelope derived from its state. Only bounded approval enables approval; non-approval scopes have no actions. | `expected_controls` equality and approval gates |
| B5 hero not replayable | All eight stages contain version/review/verification state, hashes, fixture-linked evidence, revision, stale-v0 invalidation, fresh-v1 hash, preserved-contract hash, controls, activity, and final approval scope. | `validate_hero` |

Product recheck found and closed one final corpus mismatch:
`core.06.controls.edit` is now `true`, regenerated from the same state matrix as
all other top-level and hero projections. Both validator modes pass afterward.

The product reviewer separately identified two Phase 3C integration
dependencies, outside this corpus artifact: the frontend must enforce the
state-driven control envelope rather than merely render controls, and it must
render a valid zero-action pass as `checks_passed` rather than extraction
failure. v0.2.1 does not claim frontend integration readiness until those are
closed.

Specification recheck then found and closed two fail-closed gaps:

- semantic action/property maps now require exact key coverage, not subsets;
- embedded manifest digests are bound to packaged raw artifacts. The validator
  compares exact manifests, recomputes canonical FSIR/model/config/source-map
  hashes, recomputes every execution-evidence artifact hash, and replays the
  raw classification/property/event sequence.

Four focused mutations—missing action map, empty property map, altered model
digest, and altered raw TLC-output digest—are all rejected. See
`validator-mutation-results.json`.

## Current deterministic results

- Cases: 30; levels L0/L1/L2/L3 = 8/8/8/6.
- Verdicts: 12 pass, 10 fail, 7 clarification-blocked, 1 inconclusive.
- Lowering disposition: 2 lower, 8 reject-blocking, 20 unsupported.
- Semantic mutants: 32/32 have explicit expected gates; 0/32 are reported as
  executed because no corpus→exact-FSIR materializer exists yet. See
  `mutant-results.json`. Separately, the eight `d45efd0` backend integrity/
  classification mutants were executed and rejected.
- `python3 validate_corpus.py`: pass with closed JSON Schema.
- `python3 -S validate_corpus.py`: pass with the schema-library gate explicitly
  skipped and all dependency-free semantic gates executed.
- Reproduced approved backend evidence: ordered `passed`; concurrent
  `property_violation` on the exact no-negative-cash property with normalized
  `event.buy.submit → event.buy.execute`; eight integrity/classification
  mutants rejected.
