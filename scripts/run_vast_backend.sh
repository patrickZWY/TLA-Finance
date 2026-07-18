#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "${PROJECT_ROOT}"

if [[ "${PYTHON_BIN}" == "python3" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  if [[ -z "${VLLM_API_KEY:-}" ]]; then
    echo "OPENAI_API_KEY or VLLM_API_KEY must be exported before starting the backend." >&2
    exit 1
  fi
  export OPENAI_API_KEY="${VLLM_API_KEY}"
fi

export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://127.0.0.1:18000/v1}"
export OPENAI_MODEL="${OPENAI_MODEL:-qwen3-32b}"
export OPENAI_JSON_MODE="${OPENAI_JSON_MODE:-1}"
export OPENAI_DISABLE_THINKING="${OPENAI_DISABLE_THINKING:-1}"
export OPENAI_TIMEOUT_SECONDS="${OPENAI_TIMEOUT_SECONDS:-120}"
export OPENAI_MAX_RETRIES="${OPENAI_MAX_RETRIES:-1}"
# Qwen/vLLM uses chat_template_kwargs instead of OpenAI reasoning_effort.
export OPENAI_REASONING_EFFORT=""
export SAFETY_RUN_TLC="${SAFETY_RUN_TLC:-1}"
export OBSERVE_PAYLOADS="${OBSERVE_PAYLOADS:-0}"

"${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

base_url = os.environ["OPENAI_BASE_URL"].rstrip("/")
model = os.environ["OPENAI_MODEL"]
request = urllib.request.Request(
    f"{base_url}/models",
    headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
)

try:
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
    print(
        f"Remote LLM preflight failed at {base_url}/models: {type(exc).__name__}. "
        "Check that the Vast instance is running and the SSH tunnel is bound to local port 18000.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

model_ids = {
    item.get("id")
    for item in payload.get("data", [])
    if isinstance(item, dict) and isinstance(item.get("id"), str)
}
if model not in model_ids:
    print(
        f"Configured model {model!r} was not returned by the remote endpoint; available: "
        f"{', '.join(sorted(model_ids)) or '(none)' }.",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"Remote LLM ready: {model} via {base_url}")
PY

exec "${PYTHON_BIN}" -m uvicorn api.index:app --host 127.0.0.1 --port "${PORT}"
