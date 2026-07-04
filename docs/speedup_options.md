# Speedup Options

This note captures the practical options for speeding up the current local
finance safety demo. The current bottleneck is local LLM extraction, not TLC.

## Current Measurements

Measured on this checkout with `qwen3:4b` through Ollama:

| Path | Result |
| --- | --- |
| Qwen semantic extraction, cold | 46.9s in `transform` |
| Qwen semantic extraction, warm | 13.8s in `transform` |
| Ollama placement | `100% CPU` in `ollama ps` |
| PlusCal translation, structured JSON fixture | ~203ms |
| TLC run, structured JSON fixture | ~1163ms |
| Full TLC-backed structured fixture | ~1370ms |

For this repo, the highest-value work is to move Qwen off CPU and reduce the
LLM work per request. TLC is currently small, but still has easy wins.

## Local Model Speedups

### 1. Fix CPU-only inference

`ollama ps` currently reports `100% CPU` for `qwen3:4b`. Ollama's docs say the
`PROCESSOR` column should show `100% GPU` when the model is fully loaded onto
GPU memory.

Actions:

- If this is Apple Silicon, make sure Ollama, Python, shell, and terminal are
  native arm64, not x86/Rosetta.
- If this is Intel Mac without a supported GPU path, expect local 4B inference
  to remain slow; use a smaller model or move inference to a GPU machine.
- Recheck with:

```sh
ollama ps
```

Target:

```text
PROCESSOR 100% GPU
```

### 2. Keep the model warm

Ollama unloads models after an idle period by default. Avoid cold starts during
demos by preloading the model and keeping it loaded.

Manual preload:

```sh
curl http://localhost:11434/api/chat -d '{"model":"qwen3:4b","keep_alive":"30m"}'
```

Code option in `safety/transformer.py`, inside
`OpenAIActionTransformer._try_ollama_native_structured`:

```json
"keep_alive": "30m"
```

For a dedicated demo machine, `-1` keeps the model loaded indefinitely:

```json
"keep_alive": -1
```

### 3. Reduce context and output budget

The extractor produces small JSON. The current code sets `num_predict` from
`max_tokens`, currently 512. That is generous for action extraction.

Recommended first pass:

```json
"options": {
  "temperature": 0,
  "num_ctx": 1024,
  "num_predict": 192
}
```

If extraction quality remains stable, try `num_predict: 128`.

### 4. Keep thinking disabled

The repo already does the right thing for Qwen3:

- sends `think: false` to Ollama native `/api/chat`
- prefixes Qwen3 user content with `/no_think`
- sets `OPENAI_REASONING_EFFORT=none` in demo docs/scripts

Keep these settings. Thinking mode can burn output tokens and increase latency
without helping this schema extraction task.

### 5. Benchmark smaller extractor models

For this task, correctness is more important than general reasoning. Benchmark
small structured-output-capable models against the existing semantic fixtures.

Candidates:

| Model | Why try it | Risk |
| --- | --- | --- |
| `llama3.2:3b` | Smaller than Qwen3 4B, often good instruction following | May miss finance-specific phrasing |
| `qwen3:1.7b` | Much smaller Qwen3 family model | More JSON/extraction mistakes likely |
| `phi4-mini` | Similar size to Qwen3 4B, strong structured/tool behavior | May not be faster on the same hardware |

Benchmark command:

```sh
OPENAI_BASE_URL=http://localhost:11434/v1 \
OPENAI_MODEL=llama3.2:3b \
OPENAI_REASONING_EFFORT=none \
SAFETY_RUN_TLC=0 \
.venv/bin/python -m safety.cli check \
  --actions fixtures/finance_reply.flow_bad.buy_before_transfer.md \
  --policy fixtures/policy.flow_budget600_item300.json \
  --transformer openai \
  --skip-tlc \
  --auto-decision stop
```

Track both:

- `stage=transform duration_ms`
- whether `normalized_actions.json` is semantically correct

### 6. Avoid extra model calls on `/api/chat`

The `/api/chat` path can call the model multiple times:

1. router call
2. one or more specialist tool-loop calls
3. optional synthesis call
4. safety extraction call

Options:

- Prefer `/api/semantic-check` for the workbench demo.
- For chat, make specialist agents emit a trusted `finance-actions` block and
  use `SAFETY_ACTION_TRANSFORMER=block` where appropriate.
- Add a deterministic fast path: if a valid `finance-actions` block is present,
  skip semantic LLM extraction.

### 7. Consider alternative local runtimes

Ollama is convenient, but it is not always the fastest runtime for every
machine.

Options to evaluate:

- MLX-LM on Apple Silicon, especially if prompt caching helps repeated prompts.
- BaseRT on Apple Silicon, which advertises native Metal kernels and an
  OpenAI-compatible server.
- vLLM on NVIDIA/Linux for higher-throughput hosted local inference.

Keep the app integration simple by preserving an OpenAI-compatible endpoint and
only changing `OPENAI_BASE_URL` and `OPENAI_MODEL`.

## TLA/TLC Speedups

### 1. Confirm TLC is actually the bottleneck

This repo already includes stage timing in the API response and logs:

```json
"observability": {
  "stage_durations_ms": {
    "transform": 13821,
    "formal_checks": 0
  }
}
```

If `transform` dominates, optimize the LLM first. If `formal_checks` dominates,
optimize TLC.

### 2. Skip TLC for interactive smoke tests

The Python policy mirror is immediate and catches the same action-level
violations for this demo.

Use one of:

```sh
SAFETY_RUN_TLC=0
```

or uncheck **Run PlusCal/TLC** in the UI.

Use TLC for final demo validation, order-sensitive examples, and artifact
generation.

### 3. Return policy results first, TLC later

Current `/api/semantic-check` waits for extraction, policy, artifact generation,
PlusCal, and TLC before returning.

Better interactive flow:

1. Return normalized actions and Python policy findings immediately.
2. Start PlusCal/TLC in a background task.
3. Poll or stream the TLC result into the UI when complete.

This improves perceived latency without weakening the final safety report.

### 4. Cache identical formal checks

Current run names are timestamped, so repeated identical requests regenerate
artifacts and rerun TLC.

Cache key:

```text
sha256(normalized_actions_json + policy_json + generator_version)
```

If the key exists, return the prior PlusCal/TLC report. Invalidate the cache
when `safety/tla_generator.py` changes.

### 5. Generate direct TLA+ instead of PlusCal

The generated model is already deterministic and small. Today the repo writes a
PlusCal algorithm inside a TLA file, runs `pcal.trans`, then runs TLC.

Directly generate the translated TLA operators:

- `VARIABLES`
- `Init`
- `Next`
- `Spec`
- invariants

This removes the PlusCal translator subprocess. Based on the measured fixture,
that saves roughly 200ms per TLC-enabled run and removes a whole failure mode.

### 6. Add TLC JVM and worker flags

TLC help shows `-workers auto` is supported. Local TLC output also recommends
the throughput-optimized garbage collector.

Recommended command shape:

```sh
java -XX:+UseParallelGC -Xmx2g \
  -cp "$TLAPLUS_JAR" tlc2.TLC \
  -workers auto \
  -config FinanceSafety.cfg \
  FinanceSafety.tla
```

Notes:

- For this tiny generated model, Java startup/parsing dominates, so worker
  count will not change much.
- For larger future state spaces, `-workers auto` can matter.
- If memory grows, tune `-Xmx` and TLC `-fpmem`.

### 7. Disable deadlock checking only if intentionally irrelevant

TLC supports `-deadlock`, which means "do not check for deadlock." This can
avoid work, but only use it when deadlock is not a meaningful property for the
generated model.

For the current generated finance model, termination is represented explicitly,
and the translator adds stuttering on `Done`, so deadlock checking is likely not
the core cost.

### 8. Keep generated state spaces small

For future, larger specs:

- Bound all domains tightly.
- Avoid unnecessary sequences, powersets, and high-cardinality sets.
- Add constraints only when they preserve the behavior you want checked.
- Use symmetry sets when identities are interchangeable.
- Use `VIEW` when multiple concrete states are equivalent for the property.
- Keep invariants simple and avoid expensive quantified expressions over large
  domains.

### 9. Use simulation for quick bug hunting

For large models, TLC simulation can find many bugs faster than exhaustive
model checking:

```sh
java -cp "$TLAPLUS_JAR" tlc2.TLC \
  -simulate num=1000 \
  -depth 20 \
  -config Model.cfg \
  Model.tla
```

Simulation is not exhaustive. Use it as a fast precheck, not as the final proof
of absence of reachable invariant violations.

### 10. Consider Apalache for bounded symbolic checks

Apalache performs bounded symbolic model checking with SMT. It can be useful
when TLC state enumeration grows too large, but it is incomplete beyond the
chosen bound unless you prove/check an inductive invariant.

This is not a drop-in replacement for the current PlusCal/TLC pipeline, but it
is worth evaluating if future specs grow beyond TLC's practical state space.

## Recommended Implementation Order

1. Add `keep_alive`, `num_ctx`, and lower `num_predict` in the Ollama native
   request.
2. Fix CPU-only inference or switch to a smaller extractor model.
3. Add an extractor benchmark script over semantic fixtures.
4. Cache formal check results by action/policy hash.
5. Add `-XX:+UseParallelGC`, `-workers auto`, and configurable `-Xmx` to TLC.
6. Generate direct TLA+ and remove the PlusCal translation step.
7. Make TLC asynchronous in the UI.

## Source Pointers

- Ollama API docs: https://docs.ollama.com/api
- Ollama FAQ: https://docs.ollama.com/faq
- Ollama hardware support: https://docs.ollama.com/gpu
- Ollama context length: https://docs.ollama.com/context-length
- Ollama thinking: https://docs.ollama.com/capabilities/thinking
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Qwen3 Ollama library: https://ollama.com/library/qwen3
- MLX-LM: https://github.com/ml-explore/mlx-lm
- BaseRT: https://github.com/basecompute/baseRT
- Apalache running docs: https://apalache-mc.org/docs/apalache/running.html
- TLA+ tools releases: https://github.com/tlaplus/tlaplus/releases
