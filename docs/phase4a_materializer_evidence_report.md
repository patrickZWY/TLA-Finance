# Phase 4D semantic-mutant remediation readiness

## Verdict and scope

**APPROVE FOR FRESH INDEPENDENT REVIEW** of the Phase 4A remediation descendant
of `309eda2a7a7dbccd32a18717fd7bf387ba5442fb`.

This is a readiness verdict, not independent approval. The original Phase 4A
commit remains immutable and blocked: it constructed 30 rejection records from
expected text, substituted canonical target fixtures for the two lower cases,
and validated coherently substituted evidence. This remediation closes those
findings without changing the frozen corpus or approved `d45efd0` lowering
backend.

The review scope is the closed semantic oracle, projection-to-FSIR mappings,
independent evidence replay, negative tamper gates, and refreshed evidence.
It does not approve general FSIR lowering, frontend integration, production
execution, or a refinement mapping for `core.30`.

## Frozen anchors

- Corpus archive SHA-256:
  `bf3a8b16d8a876108799dcf784331f493121570d98b4b1b3b5ec08a09925188f`
- Corpus JSON SHA-256:
  `0467b64d0148d06ed103353f4c91dc2b76ce4b45ac5b6c13412d1c8e8181c7ce`
- Original oracle-results SHA-256:
  `bcb3c1773f301a8cebce86edf66a279b1a6b3fdfc0b0568366f51b36b5ef7b76`
- Approved lowering commit:
  `d45efd09ffe5c77b89fcad1954d7959e54b7b8f3`
- TLC jar SHA-256:
  `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`

The extracted corpus passes every original `SHA256SUMS` entry. Its original
`mutant-results.json` remains unchanged and honestly reports `0/32 executed`;
remediation evidence is separate.

## Review-block closure

1. **Closed semantic oracle.** Every non-lower mutated projection is submitted
   to the independent rules in `safety/phase4a_semantic_oracles.py`. All 30
   produce an actual `SemanticOracleViolation` with deterministic class,
   message, gate code, changed paths, input hash, tool identity, and tool hash.
   Baselines are separately required to pass.
2. **Projection-derived lower input.** Each lower case starts from its
   case-declared baseline fixture and applies a declared total mapping from the
   complete semantic projection. `mapping-proof.json` binds source and tool,
   complete baseline and mutant projections, masked unchanged projection,
   mapping declaration, base fixture, derived baseline and mutant inputs, and
   the exact `control.kind`/`control.edges` executable delta. Neither derived
   input equals either canonical frozen fixture.
3. **Independent validator.** `--validate-existing` recomputes all patches and
   projections, reruns the 30 semantic oracles, rederives both lower inputs and
   mapping proofs, regenerates TLA/CFG/source maps/lowering manifests,
   reclassifies TLC output, renormalizes traces, recomputes exact reports and
   execution manifests, and checks the exact artifact tree, backend hashes,
   return codes, satisfied flags, and suite manifest.
4. **Negative tamper gate.** Focused regressions reject registry/proof drift,
   canonical-fixture substitution, backend metadata erasure, manifest or
   artifact deletion, a coherently rehashed false execution report, and
   placeholder/unexecuted states.
5. **`core.30` boundary.** All three `core.30` mutants remain reference-only,
   pre-lowering rejections with no executable artifacts or hero-evidence claim.

## Execution result

- Semantic mutants: 32/32 executed.
- Observed rejections: 32/32.
- Survivors: 0.
- Dispositions: 2 `lower`, 10 `reject_blocking`, 20 `unsupported`.
- Pre-lowering closed-oracle rejections: 30/30.
- Executable lower cases: 2/2 through projection mapping, validated FSIR,
  unchanged lowering, real TLC, exact semantic classification, strict trace
  normalization, and execution-evidence integrity.

Exact executable results:

- `mutant.17.submitted-is-settled`: derived input SHA-256
  `589b2959a398ee2bc08a1113901685f5cbeb2fd26fa025c749abcbc25da611d1`;
  TLC exit 12; `property_violation`;
  `property.safe_transfer_then_buy_order_sensitive.no_negative_cash`; events
  `event.buy.submit → event.buy.execute`.
- `mutant.18.single-trace`: derived input SHA-256
  `a5c95e31c706bd0767de4764bb6abe2783776465d5f1b22a8ace47a758fde14d`;
  TLC exit 0; `passed`; empty trace; rejected by the independently checked
  interleaving-coverage oracle.

The approved lowerer does not accept a nonzero `time_horizon`. The mapping
therefore binds the projection horizon as non-executable research metadata
while retaining executable zero in FSIR. No stronger time-horizon claim is
made.

## Reproducibility and regression evidence

- Two fresh full remediation executions are recursively byte-identical.
- Full repository suite: 165 tests passed, 3 skipped.
- Focused remediation suite: 11/11 passed.
- Frozen corpus validator with `jsonschema`: passed with exact counts.
- Frozen corpus validator under `python -S`: passed the same semantic gates;
  only the unavailable schema-library gate was skipped.
- Frozen corpus `SHA256SUMS`: all entries passed.
- Strong validation of checked evidence with the pinned TLC jar: 32 executed,
  32 rejected, 0 survivors.
- `pip check`: no broken requirements.
- Python compilation and `git diff --check`: passed.
- Backend anchor guard confirms `safety/fsir.py` and
  `safety/fsir_lowering.py` are unchanged from `d45efd0`.

Core remediation hashes:

- `semantic-mutant-results.json`:
  `09e216131b6ca6c42d2616d1732fda46243c2b8addcb8c2273c7554629abb30f`
- `suite-manifest.json`:
  `8e2246fe01a59809c6343a7d06a76c9f58d118771635846fed975b0fadd56720`
- closed oracle and total mappings:
  `bd0a8010054224c6b3e311ea5e0e18083e6167799fc1e5ca2943892288aba952`
- materializer and independent validator:
  `4562ee742cb852c2380540f7e3f061478b46392b77f5cc8686e2ec9d4f63676c`
- focused tests:
  `f7218c5b465a78e7f70bdc81d322eb6bafd9fd4dd1ccb7580d8e41fa3c543f57`
- lower mapping proofs:
  `dee9bbf36aae6174ed931221d8a075c3d1783745d64fd4a12e9ec9863bf897aa`,
  `c4986e9ecd1d02552a8678b969d1a4121ae207215216c941fdfc10d7b11c2935`

Replay:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --output "$OUTPUT"

python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --validate-existing "$OUTPUT"
```

Volatile TLC runtime metadata is deterministically elided from preserved
output; semantic diagnostics and counterexample states remain intact and are
bound by the approved execution-evidence manifest.
