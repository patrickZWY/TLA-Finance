# Phase 4A semantic-mutant materializer

This gate executes all 32 semantic-mutant oracles from the frozen Phase 3B
corpus v0.2.1 without changing that corpus. The corpus remains under
`benchmarks/phase3b-corpus-v0.2.1`; its original `mutant-results.json` honestly
continues to say `0/32 executed`. New execution evidence is written separately
under `benchmarks/phase4a-materializer-evidence`.

The runner preserves the corpus disposition boundary:

- The two `lower` mutants become validated FSIR v0.1 documents and run through
  the unchanged `d45efd0` validator, bounded lowerer, TLC classifier, strict
  trace normalizer, and execution-evidence manifest.
- The ten `reject_blocking` and twenty `unsupported` mutants are structurally
  materialized as semantic projections, then rejected by their exact
  pre-lowering disposition. They claim no TLA, CFG, source map, manifest, TLC,
  classification, or trace artifacts.

Each result preserves the original case ID, mutant ID, edit, expected gate, and
disposition. A mutation proof hashes every structural before/after edit, so a
placeholder or no-op cannot count as execution. Tests require exact `32/32`
execution, `32/32` observed rejection, `0` survivors, the `2/10/20`
distribution, no artifacts for all 30 pre-lowering cases, exact real-TLC
classification/property/trace for the two lower cases, and all evidence hashes.

Run from the repository root:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --output /tmp/phase4a-materializer
```

Validate a preserved evidence directory without rerunning TLC:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --validate-existing benchmarks/phase4a-materializer-evidence
```

The TLC seed, fingerprint index, and worker count are fixed. Volatile process,
path, and timestamp metadata is removed from `tlc-output.txt`; property
diagnostics and counterexample states are preserved verbatim and integrity
bound.
