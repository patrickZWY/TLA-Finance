# Research Evaluation Workflow

This workflow produces reviewer-facing evidence for the semantic extraction and
safety-check pipeline. It is local-first and does not require paid APIs unless
you explicitly run the live OpenAI-compatible transformer path.

## Setup

Install the normal project dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The API test client expects `httpx2`. If API tests skip with a message about
`httpx2`, reinstall from `requirements.txt`.

Optional TLC checks require Java plus `TLAPLUS_JAR` or `TLA_HOME`; see
`docs/tla_setup_macos.md`.

## Evidence Suite

Run the default evidence suite:

```sh
scripts/run_evidence_suite.sh
```

It records environment prerequisites, runs the unit/API/semantic tests with
TLC disabled, then writes a gold semantic-eval report to:

```text
artifacts/research-eval/semantic_eval_gold.json
```

Run TLC smoke checks as well:

```sh
RUN_TLC=1 scripts/run_evidence_suite.sh
```

The TLC mode runs one safe structured case and one expected-unsafe
order-sensitive case.

## Semantic Extractor Benchmark

Gold-fixture baseline:

```sh
python3 scripts/semantic_eval.py \
  --transformer gold \
  --min-pass-rate 1 \
  --min-schema-rate 1 \
  --min-exact-action-rate 1 \
  --min-finding-code-rate 1 \
  --output artifacts/research-eval/semantic_eval_gold.json
```

Live local model example:

```sh
OPENAI_BASE_URL=http://localhost:11434/v1 \
OPENAI_MODEL=qwen3:4b \
OPENAI_REASONING_EFFORT=none \
python3 scripts/semantic_eval.py \
  --transformer openai \
  --model qwen3:4b \
  --output artifacts/research-eval/semantic_eval_qwen3_4b.json
```

The report measures:

- schema-valid extraction count
- exact canonical action match
- downstream safety finding-code match
- category and risk-type pass counts
- per-case extraction latency
- raw model output and extraction errors for failed cases

Semantic cases carry reviewer-facing metadata:

- `category`: broad grouping such as `safe`, `unsafe`, or `adversarial`
- `risk_type`: the specific behavior being tested
- `expected_behavior`: short explanation of what the extractor should do

Use the same command shape with another local model or a paid API baseline by
changing `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `--model`.

## CI Threshold Gate

Use this command as the minimum CI gate for extractor regressions:

```sh
python3 scripts/semantic_eval.py \
  --transformer gold \
  --min-pass-rate 1 \
  --min-schema-rate 1 \
  --min-exact-action-rate 1 \
  --min-finding-code-rate 1 \
  --output artifacts/research-eval/semantic_eval_gold.json
```

The command exits `2` when any configured threshold is missed. The JSON report
contains a `thresholds` object with measured rates and failure messages, which
keeps CI logs and archived artifacts aligned.

## Model Comparison Matrix

First smoke-test the matrix harness without live model calls:

```sh
python3 scripts/run_model_eval_matrix.py \
  --local-models "" \
  --output-dir artifacts/research-eval/model-matrix-gold
```

Run the default local model matrix against Ollama:

```sh
ollama serve
python3 scripts/run_model_eval_matrix.py
```

By default this evaluates:

```text
qwen3:4b, llama3.2:3b, qwen3:1.7b
```

It uses `http://localhost:11434/v1` unless `OPENAI_BASE_URL` or
`SEMANTIC_EVAL_LOCAL_BASE_URL` is set.

Override local models:

```sh
python3 scripts/run_model_eval_matrix.py \
  --local-models qwen3:4b,phi4-mini \
  --local-base-url http://localhost:11434/v1
```

Relax gates for exploratory weak-model sweeps while still recording rates:

```sh
python3 scripts/run_model_eval_matrix.py \
  --min-pass-rate 0.8 \
  --min-schema-rate 0.9 \
  --min-exact-action-rate 0.8 \
  --min-finding-code-rate 0.9
```

Add a paid API baseline:

```sh
OPENAI_API_KEY=... \
python3 scripts/run_model_eval_matrix.py \
  --paid-model gpt-4o-mini
```

The command writes one report per backend plus:

```text
artifacts/research-eval/model-matrix/model_eval_matrix.json
```

Matrix runs collect failures instead of stopping at the first weak model. Add
`--fail-on-failure` when you want a non-zero exit code if any evaluated backend
misses cases.

Summarize reviewer-facing results in:

```text
docs/research_eval_report.md
```
