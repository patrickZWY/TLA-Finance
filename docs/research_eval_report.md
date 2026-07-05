# Research Evaluation Report

Generated on 2026-07-05 from the local semantic evaluation harness.

## Commands

Strict deterministic gate:

```sh
scripts/run_evidence_suite.sh
```

Live local model matrix:

```sh
python3 scripts/run_model_eval_matrix.py \
  --local-models qwen3:4b \
  --output-dir artifacts/research-eval/model-matrix-local
```

## Model Comparison

| Backend | Status | Schema valid | Exact actions | Finding codes | Median latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gold | passed | 12/12 | 12/12 | 12/12 | 0 ms | 0 ms |
| local:qwen3:4b | failed | 10/12 | 10/12 | 12/12 | 18372 ms | 33400 ms |

`qwen3:4b` now preserves downstream safety findings on every case after
deterministic post-processing. It still does not meet strict thresholds because
two model outputs drifted numerically and were rejected before policy checking.

## qwen3:4b Failure Modes

| Case | Category | Risk type | Finding match | Notes |
| --- | --- | --- | ---: | --- |
| `buy_inside_account_uses_account_as_source_and_destination` | safe | `buy_account_semantics` | yes | Changed amount from `300` to `301`; rejected as unsupported by source text. |
| `safe_transfer_then_buy_order_sensitive` | safe | `order_sensitive_safe` | yes | Changed buy amount from `300` to `30`; rejected as unsupported by source text. |

The remaining model risk is numeric drift after schema-constrained extraction.
The transformer now fails closed when a returned amount is not present as a
standalone amount in the source text, so the API can avoid checking or executing
an altered action.

## Artifacts

- Combined matrix: `artifacts/research-eval/model-matrix-local/model_eval_matrix.json`
- qwen3:4b per-case report: `artifacts/research-eval/model-matrix-local/local_qwen3_4b.json`
- Gold per-case report: `artifacts/research-eval/model-matrix-local/gold.json`
- Evidence-suite gold report: `artifacts/research-eval/semantic_eval_gold.json`

## Current Limitations

- Only `qwen3:4b` was available from local Ollama during this run.
- No paid API baseline was run because `OPENAI_API_KEY` was not set.
- The fixture currently has 12 cases, so rates are useful for regression
  detection but not yet statistically broad.
- TLC smoke checks are optional in the evidence suite; run with `RUN_TLC=1` when
  Java/TLA+ tools are available and local socket access is permitted.

## Next Steps

1. Pull and run a smaller local model, such as `llama3.2:3b` or `qwen3:1.7b`,
   to complete the local comparison table.
2. Run one paid baseline with the same fixture and strict thresholds.
3. Add a retry or constrained repair path for unsupported amount drift, then
   compare whether it improves qwen without masking unsafe output.
4. Grow the fixture toward at least 30 cases before treating percentages as
   reviewer-grade accuracy claims.
