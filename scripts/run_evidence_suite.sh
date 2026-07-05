#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_TLC="${RUN_TLC:-0}"
EVIDENCE_DIR="${EVIDENCE_DIR:-artifacts/research-eval}"

if [[ "${PYTHON_BIN}" == "python3" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

mkdir -p "${EVIDENCE_DIR}"

echo "== Environment =="
"${PYTHON_BIN}" --version
"${PYTHON_BIN}" - <<'PY'
import importlib.util as util
import os

for name in ("openai", "fastapi", "httpx2", "pydantic"):
    print(f"{name}: {'installed' if util.find_spec(name) else 'missing'}")
print(f"OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL', '(unset)')}")
print(f"OPENAI_MODEL: {os.getenv('OPENAI_MODEL', '(unset)')}")
print(f"TLAPLUS_JAR: {os.getenv('TLAPLUS_JAR', '(unset)')}")
print(f"TLA_HOME: {os.getenv('TLA_HOME', '(unset)')}")
PY

echo
echo "== Unit, API, and fixture tests =="
SAFETY_RUN_TLC=0 "${PYTHON_BIN}" -m unittest discover -s tests

echo
echo "== Semantic fixture evaluation =="
"${PYTHON_BIN}" scripts/semantic_eval.py \
  --transformer gold \
  --min-pass-rate 1 \
  --min-schema-rate 1 \
  --min-exact-action-rate 1 \
  --min-finding-code-rate 1 \
  --output "${EVIDENCE_DIR}/semantic_eval_gold.json"

if [[ "${RUN_TLC}" == "1" ]]; then
  echo
  echo "== TLC smoke checks =="
  "${PYTHON_BIN}" - <<'PY'
from safety.checker import find_tla_tools_jar

jar = find_tla_tools_jar()
if jar is None:
    raise SystemExit("RUN_TLC=1 requires TLAPLUS_JAR or TLA_HOME to point to tla2tools.jar.")
print(f"TLA+ tools: {jar}")
PY
  "${PYTHON_BIN}" -m safety.cli check \
    --actions fixtures/actions.safe.json \
    --policy fixtures/policy.dev.json \
    --artifact-dir "${EVIDENCE_DIR}/tlc" \
    --run-name evidence_safe \
    --auto-decision stop

  set +e
  "${PYTHON_BIN}" -m safety.cli check \
    --actions fixtures/finance_reply.flow_bad.buy_before_transfer.md \
    --policy fixtures/policy.flow_budget600_item300.json \
    --transformer block \
    --artifact-dir "${EVIDENCE_DIR}/tlc" \
    --run-name evidence_order_violation \
    --auto-decision stop
  status=$?
  set -e
  if [[ "${status}" != "2" ]]; then
    echo "Expected unsafe TLC smoke check to return 2, got ${status}." >&2
    exit 1
  fi
else
  echo
  echo "== TLC smoke checks skipped =="
  echo "Set RUN_TLC=1 to run one safe case and one expected-unsafe order-sensitive case."
fi

echo
echo "Evidence suite complete. Reports are under ${EVIDENCE_DIR}."
