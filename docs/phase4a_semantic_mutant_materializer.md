# Phase 4A semantic-mutant materializer

This gate executes all 32 semantic-mutant oracles from the frozen Phase 3B
corpus v0.2.1 without changing that corpus. The corpus remains under
`benchmarks/phase3b-corpus-v0.2.1`; its original `mutant-results.json` honestly
continues to say `0/32 executed`. New execution evidence is written separately
under `benchmarks/phase4a-materializer-evidence`.

The runner preserves the corpus disposition boundary:

- The two `lower` mutants are derived from the full mutated semantic projection
  by the declared total mappings in `safety/phase4a_semantic_oracles.py`.
  Mapping proofs bind the baseline and mutated projection hashes, declared
  mapping, source and tool identities, base fixture, derived baseline, derived
  mutant, and exact executable delta. The derived FSIR documents then run
  through the unchanged `d45efd0` validator, bounded lowerer, TLC classifier,
  strict trace normalizer, and execution-evidence manifest.
- The ten `reject_blocking` and twenty `unsupported` mutants are structurally
  materialized as semantic projections and actually submitted to a closed
  semantic oracle independent from the patch registry. Every rejection records
  the actual exception class, message, gate code, changed paths, tool identity,
  and input hash. They claim no TLA, CFG, source map, manifest, TLC,
  classification, or trace artifacts.

Each result preserves the original case ID, mutant ID, edit, expected gate, and
disposition. A mutation proof hashes every structural before/after edit, so a
placeholder or no-op cannot count as execution.

Validation is an independent replay, not a manifest-only check. It recomputes
the corpus projection and patch proof for all 32 mutants, reruns all 30 closed
semantic oracles, rederives both lower FSIR inputs and mapping proofs, regenerates
the TLA/CFG/source map/lowering manifest, reclassifies preserved TLC output,
renormalizes traces, recomputes execution reports, and checks exact artifact
sets and every manifest hash. Tests require exact `32/32` execution, `32/32`
observed rejection, `0` survivors, the `2/10/20` distribution, no artifacts for
all 30 pre-lowering cases, exact real-TLC classification/property/trace for the
two lower cases, and all evidence hashes.

The negative gate includes registry/proof drift, canonical-fixture
substitution, backend metadata erasure, manifest or artifact deletion,
coherently rehashed false reports, and placeholder/unexecuted results.

Run from the repository root:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --output /tmp/phase4a-materializer
```

Validate a preserved evidence directory by independently replaying everything
except TLC itself. Supplying the pinned jar also rebinds its identity:

```bash
python3 scripts/materialize_phase3b_mutants.py \
  --corpus benchmarks/phase3b-corpus-v0.2.1 \
  --tla-tools-jar "$TLA_TOOLS_JAR" \
  --validate-existing benchmarks/phase4a-materializer-evidence
```

The TLC seed, fingerprint index, and worker count are fixed. Volatile process,
path, and timestamp metadata is removed from `tlc-output.txt`; property
diagnostics and counterexample states are preserved verbatim and integrity
bound.

Core case `core.30` remains reference-only and pre-lowering. No stage 3–8
refinement mapping or hero evidence is claimed for it.
