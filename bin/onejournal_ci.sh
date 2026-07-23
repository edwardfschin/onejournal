#!/usr/bin/env bash
#
# Provider-neutral clean-checkout validation for OneJournal.
#
# This intentionally excludes the private/runtime baseline checks that require
# broker evidence, local environment files, generated output, or the journal DB.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ONEJOURNAL_PYTHON:-python}"
FIXTURE="docs/examples/manual_csv/fills_template.csv"
ASOF="2026-06-02"

cd "$PROJECT_DIR"

echo "===== OneJournal clean CI ====="
echo "PYTHON    : $("$PYTHON_BIN" --version 2>&1)"
echo "ROOT      : $PROJECT_DIR"
echo "PRIVATE   : not required"
echo "BROKER API: disabled"

"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -c "import duckdb, requests, streamlit, yaml; import onejournal; print('IMPORTS   : OK')"
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
