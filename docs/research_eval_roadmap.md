# Research Roadmap For Technical Reviewers

## Summary

Recommended next step: build a reproducible extractor-evaluation package comparing local models against one paid API baseline, with safety-check agreement as secondary evidence. This matches the chosen direction: research depth, technical reviewers, a roadmap-sized milestone, hybrid comparison, and extractor evals.

Current repo baseline:

- Core offline tests pass: `72 tests`, `OK`, `26 skipped`.
- Skips are due to missing `httpx2` for FastAPI TestClient.
- Active Python also lacks `openai`, so live extractor/API evidence is not currently reproducible from this environment.

## Key Workstreams

### 1. Reproducible evidence setup

- Add or adjust dev dependencies so API tests run instead of skipping.
- Add a single command for the reviewer evidence suite: unit tests, API tests, semantic fixture evals, and optional TLC checks.
- Record environment prerequisites: Python version, Ollama version, model names, Java/TLA setup.

### 2. Extractor benchmark suite

- Expand `fixtures/semantic_codex_cases.json` into a labeled eval set with safe cases, unsafe cases, omitted-action cases, prompt-injection attempts, missing-field prose, order-sensitive transfer/buy flows, and multi-action budget cases.
- Benchmark at least:
  - local current default: `qwen3:4b`
  - one smaller local model, such as `llama3.2:3b` or `qwen3:1.7b`
  - one paid API baseline
- Measure schema validity, exact action match, finding-code match after policy validation, extraction latency, and failure mode.

### 3. Runtime optimization before formal-method optimization

- Tune the Ollama native request first: set `keep_alive`, lower `num_predict` from `512`, and add a bounded `num_ctx`.
- Keep `think: false`, schema-constrained output, and `temperature: 0`; current Ollama docs support these choices.
- Treat TLC speedups as secondary because repo measurements show local LLM extraction dominates latency.

### 4. Reviewer-facing report

- Produce a short `docs/research_eval_report.md` with:
  - model comparison table
  - representative success/failure examples
  - action extraction accuracy
  - downstream safety finding accuracy
  - latency distribution
  - known limitations
- Include links to generated artifacts for 2-3 canonical cases, especially the order-sensitive balance violation.

## Test Plan

- Run `python3 -m unittest discover -s tests` with no skipped API tests.
- Run the semantic eval suite against mocked fixtures and live model backends.
- Run at least one TLC-enabled safe case and one TLC-enabled unsafe order-sensitive case.
- Verify extraction failures fail closed and preserve raw model output for debugging.

## Assumptions

- The next milestone is for technical reviewers, not external demo users.
- Hybrid comparison means local-first plus one paid API baseline, not full cloud deployment.
- The current workbench remains the main artifact; this roadmap adds evidence and benchmarking around it.
- Sources checked:
  - [Ollama Chat API](https://docs.ollama.com/api/chat)
  - [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
  - [Ollama Thinking](https://docs.ollama.com/capabilities/thinking)
  - [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  - [TLA+ TLC docs](https://docs.tlapl.us/using%3Atlc%3Astart)
