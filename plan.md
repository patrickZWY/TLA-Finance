# TLA-Finance Plan

## Potential Future Direction: Fast Local LLMs With Small Composable Specs

- On a future Apple Silicon Mac, evaluate Uzu as a local inference backend for
  faster chat generation and semantic extraction.
- Keep Uzu behind the existing transformer boundary rather than coupling it to
  the safety checker directly.
- Use faster inference to support more frequent checks over small, composable
  TLA+/PlusCal artifacts instead of generating one large monolithic spec.
- Preserve the current feedback loop:
  natural finance text -> canonical action JSON -> Python policy checks ->
  targeted TLA+/TLC checks -> aggregated findings.
- Benchmark any Uzu path against the current Ollama/OpenAI-compatible path on
  schema validity, action extraction accuracy, safety finding agreement, and
  latency before adopting it.

