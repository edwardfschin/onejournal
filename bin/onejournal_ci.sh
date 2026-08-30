#!/usr/bin/env bash
#
# Provider-neutral clean-checkout validation for OneJournal.
#
# This intentionally excludes the private/runtime baseline checks that require
# broker evidence, local environment files, generated output, or the journal DB.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
if [ -n "${ONEJOURNAL_PYTHON:-}" ]; then
  PYTHON_BIN="${ONEJOURNAL_PYTHON}"
elif [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
elif [ -x "${PROJECT_DIR}/.venv/bin/python3" ]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python3"
elif [ -x "${PROJECT_DIR}/.venv/bin/python3.13" ]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python3.13"
elif [ -x "${HOME}/python-envs/onejournal-env/bin/python" ]; then
  # The documented shared local OneJournal environment may live outside the
  # checkout; keep CI on the canonical repository while using that interpreter.
  PYTHON_BIN="${HOME}/python-envs/onejournal-env/bin/python"
elif command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="python3.13"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "FAIL: unable to find python executable (python or python3)." >&2
  exit 1
fi
FIXTURE="docs/examples/manual_csv/fills_template.csv"
ASOF="2026-06-02"

cd "$PROJECT_DIR"

echo "===== OneJournal clean CI ====="
echo "PYTHON    : $("$PYTHON_BIN" --version 2>&1)"
echo "ROOT      : $PROJECT_DIR"
echo "PRIVATE   : not required"
echo "BROKER API: disabled"

"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -c "import duckdb, streamlit, yaml; import onejournal; print('IMPORTS   : OK')"
PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/onejournal_ci_pycache" \
    "$PYTHON_BIN" -m compileall -q src scripts/journal scripts/ci tests
"$PYTHON_BIN" scripts/ci/check_repository.py
"$PYTHON_BIN" -m unittest discover -s tests -p "test_*.py" -v
"$PYTHON_BIN" scripts/journal/check_normalized_fills_contract.py \
    --asof "$ASOF" --file "$FIXTURE"
"$PYTHON_BIN" scripts/journal/check_manual_fills.py \
    --asof "$ASOF" --file "$FIXTURE"
"$PYTHON_BIN" scripts/journal/check_trade_episodes.py \
    --asof "$ASOF" --file "$FIXTURE"
"$PYTHON_BIN" scripts/journal/check_dashboard_payload.py \
    --asof "$ASOF" --file "$FIXTURE"

echo "PASS OneJournal clean CI checks passed."
