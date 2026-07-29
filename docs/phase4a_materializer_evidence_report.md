# Phase 4A semantic-mutant materializer evidence

## Readiness verdict

**APPROVE FOR INDEPENDENT REVIEW** on the frozen Phase 3B corpus v0.2.1 and
bounded `d45efd0` lowering scope.

This is a readiness verdict, not independent approval and not approval of
general FSIR lowering, frontend integration, or production execution.

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
`mutant-results.json` remains unchanged and continues to report `0/32
executed`; Phase 4A evidence is separate.

## Execution result

- Semantic mutants: 32/32 executed.
- Observed rejections: 32/32.
- Survivors: 0.
- Dispositions: 2 `lower`, 10 `reject_blocking`, 20 `unsupported`.
- Pre-lowering rejections: 30/30, with no executable artifacts claimed.
- Executable lower cases: 2/2 through validated FSIR, deterministic lowering,
  real TLC, exact classification/property/trace checks, strict trace
  normalization, and execution-evidence integrity.

Exact executable results:

- `mutant.17.submitted-is-settled`: TLC exit 12,
  `property_violation`,
  `property.safe_transfer_then_buy_order_sensitive.no_negative_cash`, events
  `event.buy.submit → event.buy.execute`.
- `mutant.18.single-trace`: TLC exit 0, `passed`, no violated property and no
  counterexample events; the corpus interleaving-coverage oracle rejects the
  settlement-only mutant.

Every mutant has a nonempty structural mutation proof, distinct baseline and
mutated projection hashes, an executed semantic-oracle record, its unchanged
case/mutant/edit/expected-gate/disposition fields, and an explicit survivor
verdict. Placeholder and unexecuted states fail validation.

## Reproducibility and regression evidence

- Two fresh full materializer executions were byte-identical recursively.
- Full repository suite: 159 tests passed, 3 skipped.
- Focused materializer suite: 5/5 passed.
- Frozen corpus validator with `jsonschema`: passed with exact
  30-case, 2/8/20-case-disposition, and 32-oracle counts.
- Frozen corpus validator under `python -S`: same semantic gates and counts,
  with only the schema-library gate skipped.
- `pip check`: no broken requirements.
- Python compilation: passed.
- Backend anchor guard confirms `safety/fsir.py` and
  `safety/fsir_lowering.py` are unchanged from `d45efd0`.

Toolchain:

- Python 3.12.3
- Pydantic 2.13.4
- OpenJDK 21.0.11
- TLC 2.19 jar at the frozen hash above
- lowerer/source-map/lowering-manifest/execution-manifest versions:
  `fsir-tla-lowerer-0.1`, `fsir-tla-source-map-0.1`,
  `fsir-tla-manifest-0.1`, `fsir-tla-execution-evidence-0.1`

Core Phase 4A hashes:

- `semantic-mutant-results.json`:
  `76c758af33f51fe2cfd9e0770e8d9e34f8aa74d64824b892b6d0a83afd438d81`
- `suite-manifest.json`:
  `d2ca6443fd252cf2cb1f55a83efe35a2a516795c5094a84182834fa4089bc15b`
- materializer:
  `25e6bd576e45210794e8bba86d7de230751f4cf608a63839b258a1c60752eb87`
- focused tests:
  `35c2c9734bad50d3618b82d9483c7dd287ad340c3ca0dc1e745bb9986625dfca`

Replay:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --output "$OUTPUT"
```

Volatile TLC runtime metadata is deterministically elided from preserved
output; semantic diagnostics and counterexample states remain intact and are
bound by the approved execution-evidence manifest.
