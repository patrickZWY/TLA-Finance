#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PUBLIC_DEMO_HOSTNAME="${PUBLIC_DEMO_HOSTNAME:-demo.zhengwangyuan-patrick.com}"

if [[ "${PYTHON_BIN}" == "python3" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

export CLOUDFLARE_HOSTNAME="${CLOUDFLARE_HOSTNAME:-live-demo.zhengwangyuan-patrick.com}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://localhost:11434/v1}"
export OPENAI_MODEL="${OPENAI_MODEL:-qwen3:4b}"
export OPENAI_REASONING_EFFORT="${OPENAI_REASONING_EFFORT:-none}"
export SAFETY_RUN_TLC="${SAFETY_RUN_TLC:-1}"
export OBSERVE_PAYLOADS="${OBSERVE_PAYLOADS:-0}"
export SAFETY_ARTIFACT_RETENTION_HOURS="${SAFETY_ARTIFACT_RETENTION_HOURS:-24}"
export SAFETY_TLA_TIMEOUT_SECONDS="${SAFETY_TLA_TIMEOUT_SECONDS:-60}"

if [[ -n "${CLOUDFLARE_HOSTNAME:-}" ]]; then
  export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-https://${PUBLIC_DEMO_HOSTNAME},https://${CLOUDFLARE_HOSTNAME}}"
  export ALLOWED_HOSTS="${ALLOWED_HOSTS:-${PUBLIC_DEMO_HOSTNAME},${CLOUDFLARE_HOSTNAME},127.0.0.1,localhost}"
fi

exec "${PYTHON_BIN}" -m uvicorn api.index:app --host 127.0.0.1 --port "${PORT}"
