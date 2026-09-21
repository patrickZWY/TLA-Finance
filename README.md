# TLA-Finance

TLA-Finance is a local finance safety workbench. You paste ambiguous finance
advice into a browser UI, an OpenAI-compatible model normalizes it into
concrete action JSON, and those actions are checked by deterministic Python
policy rules plus an optional PlusCal/TLA+ model-checking pass (TLC) that
surfaces order-sensitive violations such as buying before a transfer settles.
A second, closed path accepts typed FSIR documents (or frozen corpus cases)
and produces hash-bound TLC evidence with fail-closed approval controls. This
is local demo software: it never connects to banks, brokerages, or payment
systems, and nothing in it is licensed financial advice.

## Quick start

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Pick one model path in `.env`. The recommended local path is Ollama:

```sh
ollama pull qwen3:4b
ollama serve
```

```sh
# .env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen3:4b
OPENAI_REASONING_EFFORT=none
```

For the paid path set `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-4o-mini` instead.
Then start the app:

```sh
python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The prose path runs from the main screen. The
bounded FSIR path is driven by query parameters, for example
`?case=core.17` (verified pass), `?case=core.18` (exact counterexample),
`?case=core.06` (intentional no-action), and `?case=core.30&stage=4`
(reference-only audit with approval disabled).

The scenario picker also includes two standalone verification benchmarks:

- a fixed 100-action plan whose first balance violation occurs at action 100;
- an eight-round, four-way branching model with 65,536 possible decision
  histories. This benchmark runs TLC without the Python policy mirror and
  reports the exact counterexample path and explored-state count.

TLC needs Java plus `tla2tools.jar`, located through `TLAPLUS_JAR` or
`TLA_HOME`, or discovered from the TLA+ VS Code extension; see
[docs/tla_setup_macos.md](docs/tla_setup_macos.md). Without
it, uncheck **Run PlusCal/TLC** in the UI; TLC-backed runs report
`not_configured` and the Python policy checks still run.

## Test

```sh
SAFETY_RUN_TLC=0 python3 -m unittest discover -s tests
```

`scripts/run_evidence_suite.sh` runs the same tests plus the gold semantic
benchmark; add `RUN_TLC=1` for TLC smoke checks.

## Where to go next

- [docs/bounded_agent_workbench.md](docs/bounded_agent_workbench.md): API
  contract, evidence boundary, and controls for the closed FSIR path.
- [docs/safety_gate_mvp.md](docs/safety_gate_mvp.md): the safety agent,
  policy invariants, and fixture flows.
- [docs/reference.md](docs/reference.md): API routes, policy and action
  schemas, CLI commands, environment variables, and project layout.
- [docs/cloudflare_one_demo.md](docs/cloudflare_one_demo.md): serving the local
  app through a Cloudflare tunnel for invited testers.
- [docs/remote_vllm_backend.md](docs/remote_vllm_backend.md): using a rented
  vLLM server over an SSH tunnel instead of Ollama.
- [docs/research_eval_workflow.md](docs/research_eval_workflow.md): the
  semantic extractor benchmark and multi-model matrix;
  [docs/research_eval_report.md](docs/research_eval_report.md) has results.
- [docs/fsir_v0.1.md](docs/fsir_v0.1.md) and
  [docs/fsir_lowering_v0.1.md](docs/fsir_lowering_v0.1.md): the typed IR and
  its bounded lowering to TLA+.
- [benchmarks/phase3b-corpus-v0.2.1/README.md](benchmarks/phase3b-corpus-v0.2.1/README.md):
  the frozen 30-case corpus behind the bounded path.
- [plan.md](plan.md): possible future directions.
