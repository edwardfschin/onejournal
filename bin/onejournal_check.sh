#!/usr/bin/env bash
# bin/onejournal_check.sh
#
# Purpose
# -------
# Validate the local OneJournal baseline setup.
# This script does not fetch broker data, does not write journal data,
# and does not place orders.

set -u
set -o pipefail
set +e

PROJECT_DIR="/Users/edward/Library/Mobile Documents/com~apple~CloudDocs/Projects/onejournal"
VENV_DIR="/Users/edward/python-envs/onejournal-env"
PRIVATE_DIR="/Users/edward/.onejournal"
PY="$VENV_DIR/bin/python"

fail_count=0

check_path() {
  label="$1"
  path="$2"
  if [ -e "$path" ]; then
    echo "OK   $label: $path"
  else
    echo "FAIL $label missing: $path"
    fail_count=$((fail_count + 1))
  fi
}

check_file_contains() {
  label="$1"
  path="$2"
  pattern="$3"
  if [ ! -f "$path" ]; then
    echo "FAIL $label missing file: $path"
    fail_count=$((fail_count + 1))
    return
  fi
  if grep -q -- "$pattern" "$path"; then
    echo "OK   $label: $pattern"
  else
    echo "FAIL $label missing pattern: $pattern in $path"
    fail_count=$((fail_count + 1))
  fi
}

check_file_not_contains() {
  local label="$1"
  local file="$2"
  local pattern="$3"
  if grep -Fq -- "$pattern" "$file"; then
    echo "FAIL $label forbidden pattern present: $pattern in $file"
    fail_count=$((fail_count + 1))
  else
    echo "OK   $label: forbidden pattern absent"
  fi
}

echo "===== OneJournal baseline check ====="
echo "PROJECT_DIR=$PROJECT_DIR"
echo "VENV_DIR=$VENV_DIR"
echo "PRIVATE_DIR=$PRIVATE_DIR"
echo

echo "===== Core paths ====="
check_path "PROJECT_DIR" "$PROJECT_DIR"
check_path "VENV_DIR" "$VENV_DIR"
check_path "PRIVATE_DIR" "$PRIVATE_DIR"
check_path "Python" "$PY"
check_path "bin/onejournal_git_status.sh" "$PROJECT_DIR/bin/onejournal_git_status.sh"
check_file_contains "git guard identity title" "$PROJECT_DIR/bin/onejournal_git_status.sh" "ONEJOURNAL GIT IDENTITY"
check_file_contains "git guard top mismatch" "$PROJECT_DIR/bin/onejournal_git_status.sh" "git top-level mismatch"
check_file_contains "git guard pass" "$PROJECT_DIR/bin/onejournal_git_status.sh" "ONEJOURNAL_GIT_GUARD=PASS"

echo

echo "===== Python/package ====="
if [ -x "$PY" ]; then
  "$PY" --version
  "$PY" -c "import onejournal; print('OK   import onejournal', onejournal.__version__)"
  if [ $? -ne 0 ]; then
    echo "FAIL package import failed"
    fail_count=$((fail_count + 1))
  fi
else
  echo "FAIL Python is not executable: $PY"
  fail_count=$((fail_count + 1))
fi

echo

echo "===== Project config files ====="
for f in app.yaml paths.yaml brokers.yaml marketdata.yaml dashboard.yaml journal.yaml logging.yaml; do
  check_path "config/$f" "$PROJECT_DIR/config/$f"
done

echo

echo "===== Private env files ====="
for f in machine.env access.env brokers.env marketdata.env app.env; do
  check_path "env/$f" "$PRIVATE_DIR/env/$f"
done

echo

echo "===== Safety gates ====="
check_file_contains "project read-only" "$PROJECT_DIR/config/app.yaml" "allow_order_placement: false"
check_file_contains "journal read-only" "$PROJECT_DIR/config/journal.yaml" "allow_order_placement: false"
check_file_contains "machine order block" "$PRIVATE_DIR/env/machine.env" "ONEJOURNAL_CAN_PLACE_ORDERS=0"

echo

echo "===== Manual CSV adapter ====="
check_path "src/onejournal/brokers/manual_csv/adapter.py" "$PROJECT_DIR/src/onejournal/brokers/manual_csv/adapter.py"
if [ -x "$PY" ]; then
  "$PY" -c "from onejournal.brokers.manual_csv.adapter import ManualCsvAdapter; a=ManualCsvAdapter(); print('OK   manual csv adapter import', a.source_broker)"
  if [ $? -ne 0 ]; then
    echo "FAIL manual csv adapter import failed"
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Broker adapter base ====="
check_path "src/onejournal/brokers/base.py" "$PROJECT_DIR/src/onejournal/brokers/base.py"
if [ -x "$PY" ]; then
  "$PY" -c "from onejournal.brokers.base import BrokerAdapter, BrokerAdapterResult; print('OK   broker adapter base import')"
  if [ $? -ne 0 ]; then
    echo "FAIL broker adapter base import failed"
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Broker normalization ====="
check_path "src/onejournal/brokers/normalized.py" "$PROJECT_DIR/src/onejournal/brokers/normalized.py"
if [ -x "$PY" ]; then
  "$PY" -c "from onejournal.brokers.normalized import NormalizedAccount, NormalizedOrder, NormalizedFill, NormalizedPosition, NormalizedTransaction; print('OK   broker normalized records import')"
  if [ $? -ne 0 ]; then
    echo "FAIL broker normalized records import failed"
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Streamlit dashboard app ====="
check_path "src/onejournal/apps/streamlit_app.py" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py"
if [ -x "$PY" ]; then
  "$PY" -c "import streamlit; from onejournal.apps.streamlit_app import load_payload; from pathlib import Path; payload=load_payload(Path('output/dashboard/latest/dashboard_payload.json')); print('OK   streamlit dashboard app import', payload['metadata']['auto_trade'])"
  "$PY" -c "from onejournal.apps.streamlit_app import DEFAULT_PAYLOAD_PATH, DEFAULT_DB_PAYLOAD_PATH; print('OK   streamlit payload defaults', DEFAULT_PAYLOAD_PATH.name, DEFAULT_DB_PAYLOAD_PATH.name)"
  if [ $? -ne 0 ]; then
    echo "FAIL streamlit dashboard app import failed"
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Dashboard payload ====="
check_path "src/onejournal/dashboard/payload.py" "$PROJECT_DIR/src/onejournal/dashboard/payload.py"
check_path "scripts/journal/check_dashboard_payload.py" "$PROJECT_DIR/scripts/journal/check_dashboard_payload.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/check_dashboard_payload.py" --asof 2026-06-02 --file "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" --output "$PROJECT_DIR/output/dashboard/latest/dashboard_payload.json" --write >/tmp/onejournal_dashboard_payload_check.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_dashboard_payload_check.out; then
    echo "OK   dashboard payload check"
  else
    echo "FAIL dashboard payload check failed"
    cat /tmp/onejournal_dashboard_payload_check.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Trade episode preview ====="
check_path "src/onejournal/journal/episodes.py" "$PROJECT_DIR/src/onejournal/journal/episodes.py"
check_path "scripts/journal/check_trade_episodes.py" "$PROJECT_DIR/scripts/journal/check_trade_episodes.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/check_trade_episodes.py" --asof 2026-06-02 --file "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" >/tmp/onejournal_episode_check.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_episode_check.out; then
    echo "OK   trade episode preview check"
  else
    echo "FAIL trade episode preview check failed"
    cat /tmp/onejournal_episode_check.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Manual fills check script ====="
check_path "scripts/journal/check_manual_fills.py" "$PROJECT_DIR/scripts/journal/check_manual_fills.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/check_manual_fills.py" --asof 2026-06-02 --file "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" >/tmp/onejournal_manual_fills_check.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_manual_fills_check.out; then
    echo "OK   manual fills check script"
  else
    echo "FAIL manual fills check script failed"
    cat /tmp/onejournal_manual_fills_check.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Manual CSV parser ====="
check_path "src/onejournal/brokers/manual_csv/fills.py" "$PROJECT_DIR/src/onejournal/brokers/manual_csv/fills.py"
if [ -x "$PY" ]; then
  "$PY" -c "from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv; records=parse_manual_fills_csv('docs/examples/manual_csv/fills_template.csv'); print('OK   manual fills parser', len(records), records[0].fill_uid)"
  if [ $? -ne 0 ]; then
    echo "FAIL manual fills parser failed"
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Manual CSV examples ====="
check_path "docs/examples/manual_csv/fills_template.csv" "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv"
check_file_contains "manual fills asof" "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" "asof,source_broker"
check_file_contains "manual fills option fields" "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" "option_symbol,underlying_symbol,option_type,expiry,strike"

echo

echo "===== Normalized Fills Contract ====="
check_path "scripts/journal/check_normalized_fills_contract.py" "$PROJECT_DIR/scripts/journal/check_normalized_fills_contract.py"
check_path "docs/normalized_fills_validation_contract.md" "$PROJECT_DIR/docs/normalized_fills_validation_contract.md"
check_file_contains "normalized fills validation command" "$PROJECT_DIR/docs/normalized_fills_validation_contract.md" "check_normalized_fills_contract.py --asof"
check_file_contains "normalized fills validation transport" "$PROJECT_DIR/docs/normalized_fills_validation_contract.md" "Normalized fills CSV is transport"
check_file_contains "script inventory normalized fills checker" "$PROJECT_DIR/docs/script_inventory.md" "check_normalized_fills_contract.py"
if "$PY" "$PROJECT_DIR/scripts/journal/check_normalized_fills_contract.py" --asof 2026-06-02 --file "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" >/tmp/onejournal_normalized_fills_contract.out 2>/tmp/onejournal_normalized_fills_contract.err; then
  echo "OK   normalized fills contract"
else
  echo "FAIL normalized fills contract"
  cat /tmp/onejournal_normalized_fills_contract.out
  cat /tmp/onejournal_normalized_fills_contract.err
  fail_count=$((fail_count + 1))
fi
echo

echo "===== Strategy classification check ====="
check_path "scripts/journal/check_strategy_classification.py" "$PROJECT_DIR/scripts/journal/check_strategy_classification.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/check_strategy_classification.py" --asof 2026-06-02 --payload "$PROJECT_DIR/output/dashboard/latest/dashboard_payload.json" >/tmp/onejournal_strategy_classification.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_strategy_classification.out; then
    echo "OK   strategy classification check"
  else
    echo "FAIL strategy classification check failed"
    cat /tmp/onejournal_strategy_classification.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Dashboard refresh runner ====="
check_path "scripts/journal/refresh_dashboard.py" "$PROJECT_DIR/scripts/journal/refresh_dashboard.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/refresh_dashboard.py" --asof 2026-06-02 --file "$PROJECT_DIR/docs/examples/manual_csv/fills_template.csv" --reviews "$PROJECT_DIR/data/journal/reviews/manual_reviews.csv" --output "$PROJECT_DIR/output/dashboard/latest/dashboard_payload.json" >/tmp/onejournal_refresh_dashboard.out 2>&1
  rc=$?
  if [ $rc -eq 0 ] && [ -f "$PROJECT_DIR/output/dashboard/latest/dashboard_payload.json" ]; then
    echo "OK   dashboard refresh runner"
  else
    echo "FAIL dashboard refresh runner failed rc=$rc"
    cat /tmp/onejournal_refresh_dashboard.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Review template updater ====="
check_path "scripts/journal/update_review_template.py" "$PROJECT_DIR/scripts/journal/update_review_template.py"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/update_review_template.py" --asof 2026-06-02 --payload "$PROJECT_DIR/output/dashboard/latest/dashboard_payload.json" --reviews "$PROJECT_DIR/data/journal/reviews/manual_reviews.csv" >/tmp/onejournal_review_template.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_review_template.out; then
    echo "OK   review template updater"
  else
    echo "FAIL review template updater failed"
    cat /tmp/onejournal_review_template.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Journal DuckDB ====="
check_path "scripts/journal/init_journal_db.py" "$PROJECT_DIR/scripts/journal/init_journal_db.py"
check_path "scripts/journal/import_journal_to_db.py" "$PROJECT_DIR/scripts/journal/import_journal_to_db.py"
check_path "scripts/journal/check_journal_db.py" "$PROJECT_DIR/scripts/journal/check_journal_db.py"
check_path "scripts/journal/build_dashboard_payload_from_db.py" "$PROJECT_DIR/scripts/journal/build_dashboard_payload_from_db.py"
check_path "scripts/journal/upsert_manual_review_to_db.py" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py"
check_path "data/journal/onejournal.duckdb" "$PROJECT_DIR/data/journal/onejournal.duckdb"
if [ -x "$PY" ]; then
  "$PY" "$PROJECT_DIR/scripts/journal/check_journal_db.py" --db "$PROJECT_DIR/data/journal/onejournal.duckdb" >/tmp/onejournal_db_check.out 2>&1
  if [ $? -eq 0 ] && grep -q "STATUS    : OK" /tmp/onejournal_db_check.out; then
    echo "OK   journal db check"
  else
    echo "FAIL journal db check failed"
    cat /tmp/onejournal_db_check.out
    fail_count=$((fail_count + 1))
  fi
fi

echo

echo "===== Operator quickstart doc ====="
check_path "docs/operator_quickstart.md" "$PROJECT_DIR/docs/operator_quickstart.md"
check_file_contains "operator quickstart title" "$PROJECT_DIR/docs/operator_quickstart.md" "OneJournal Operator Quickstart"
check_file_contains "operator quickstart db payload build" "$PROJECT_DIR/docs/operator_quickstart.md" "python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02"
check_file_contains "operator quickstart no auto-trade" "$PROJECT_DIR/docs/operator_quickstart.md" "No auto-trade"
check_file_contains "operator quickstart episode group" "$PROJECT_DIR/docs/operator_quickstart.md" "episode_group_id"
check_file_contains "episode primary symbol helper" "$PROJECT_DIR/src/onejournal/journal/episodes.py" "def _primary_symbol_for_episode"
check_file_contains "episode primary symbol quality check" "$PROJECT_DIR/scripts/journal/check_trade_episodes.py" "failed primary_symbol quality check"
check_file_contains "operator quickstart strategy list" "$PROJECT_DIR/docs/operator_quickstart.md" "Put Credit Vertical"
check_file_contains "operator quickstart stock strategy" "$PROJECT_DIR/docs/operator_quickstart.md" "Stock Long"
check_file_contains "operator quickstart phase b db source" "$PROJECT_DIR/docs/operator_quickstart.md" "Phase B review source of truth: DuckDB manual_reviews"
check_file_contains "operator quickstart db save" "$PROJECT_DIR/docs/operator_quickstart.md" "Streamlit DB payload Save Review writes DuckDB manual_reviews"

echo

echo "===== Manual review workflow doc ====="
check_path "docs/manual_review_workflow.md" "$PROJECT_DIR/docs/manual_review_workflow.md"
check_file_contains "manual review title" "$PROJECT_DIR/docs/manual_review_workflow.md" "OneJournal Manual Review Workflow"
check_file_contains "manual review phase b db source" "$PROJECT_DIR/docs/manual_review_workflow.md" "Phase B review source of truth: DuckDB manual_reviews"
check_file_contains "manual review no auto-trade" "$PROJECT_DIR/docs/manual_review_workflow.md" "auto-trade"
check_file_contains "manual review db save" "$PROJECT_DIR/docs/manual_review_workflow.md" "Streamlit DB payload Save Review writes DuckDB manual_reviews"
check_file_contains "manual review csv legacy" "$PROJECT_DIR/docs/manual_review_workflow.md" "CSV manual_reviews.csv is legacy/backfill/export only"
check_file_contains "operator quickstart db default" "$PROJECT_DIR/docs/operator_quickstart.md" "DB payload is the default Streamlit payload in Phase B."
check_file_contains "manual review db default" "$PROJECT_DIR/docs/manual_review_workflow.md" "DB payload is the default Streamlit payload in Phase B."
check_file_contains "operator quickstart csv readonly" "$PROJECT_DIR/docs/operator_quickstart.md" "CSV and Custom payloads are read-only in Phase B."
check_file_contains "manual review csv readonly" "$PROJECT_DIR/docs/manual_review_workflow.md" "CSV and Custom payloads are read-only in Phase B."
check_file_contains "db upsert order safety" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py" "does not place, cancel, or modify orders"
check_file_contains "db upsert broker safety" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py" "does not call broker APIs"
check_file_contains "db upsert episode guard table" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py" "trade_episodes"
check_file_contains "db upsert episode guard predicate" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py" "episode_uid = ?"
check_file_contains "db upsert manual_reviews" "$PROJECT_DIR/scripts/journal/upsert_manual_review_to_db.py" "INSERT OR REPLACE INTO manual_reviews"
check_file_contains "streamlit rebuilds db payload" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "build_dashboard_payload_from_db.py"
check_file_contains "streamlit calls db upsert" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "upsert_manual_review_to_db.py"
check_file_not_contains "streamlit does not call refresh_dashboard" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "refresh_dashboard.py"
check_file_not_contains "streamlit does not call update_review_template" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "update_review_template.py"
check_file_not_contains "streamlit does not reference manual_reviews_csv" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "manual_reviews.csv"
check_file_not_contains "streamlit no saved csv review" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "Saved CSV review"
check_file_not_contains "streamlit no refresh_dashboard_payload" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "def refresh_dashboard_payload("
check_file_not_contains "streamlit no save_review_row" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "def save_review_row("
check_file_not_contains "streamlit no csv save wording" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "Saves to manual_reviews.csv"
check_file_contains "streamlit csv custom readonly" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "CSV and Custom payloads are read-only in Phase B"
check_file_contains "streamlit phase b db default order" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "[\"DB payload\", \"CSV payload\", \"Custom path\"]"
check_file_contains "streamlit phase b db default text" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "DB payload is the Phase B default"
check_file_contains "streamlit phase e db writable" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "Writable mode: DB payload only"
check_file_contains "streamlit phase e save button" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "Save Review to DuckDB"
check_file_contains "streamlit phase e no order modification" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "no order modification"
check_file_not_contains "streamlit no default reviews path" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "DEFAULT_REVIEWS_PATH"
check_file_not_contains "streamlit no csv import" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "import csv"
check_file_not_contains "streamlit no load_review_rows" "$PROJECT_DIR/src/onejournal/apps/streamlit_app.py" "load_review_rows"



echo

check_file_contains "operator phase f runbook" "$PROJECT_DIR/docs/operator_quickstart.md" "Phase F Current Operator Runbook"
check_file_contains "operator phase f contract check" "$PROJECT_DIR/docs/operator_quickstart.md" "check_db_dashboard_contract.py"
check_file_contains "operator phase f save flow check" "$PROJECT_DIR/docs/operator_quickstart.md" "check_save_review_flow.py"
check_file_contains "manual phase f procedure" "$PROJECT_DIR/docs/manual_review_workflow.md" "Phase F Save Review Operating Procedure"
check_file_contains "manual phase f temp db proof" "$PROJECT_DIR/docs/manual_review_workflow.md" "temporary validation DB copy"
check_file_contains "manual phase f csv legacy" "$PROJECT_DIR/docs/manual_review_workflow.md" "CSV manual_reviews.csv remains legacy/backfill/export only"
check_file_not_contains "manual review stale csv enough" "$PROJECT_DIR/docs/manual_review_workflow.md" "For now, CSV is enough"
check_file_contains "inventory phase f guarded scripts" "$PROJECT_DIR/docs/script_inventory.md" "Phase F Guarded Review Workflow Scripts"
check_file_contains "inventory save flow checker" "$PROJECT_DIR/docs/script_inventory.md" "check_save_review_flow.py"
check_file_contains "inventory db contract checker" "$PROJECT_DIR/docs/script_inventory.md" "check_db_dashboard_contract.py"
check_path "scripts/journal/check_episode_quality_contract.py" "$PROJECT_DIR/scripts/journal/check_episode_quality_contract.py"
check_path "docs/episode_quality_contract.md" "$PROJECT_DIR/docs/episode_quality_contract.md"
check_file_contains "episode quality contract primary symbol" "$PROJECT_DIR/docs/episode_quality_contract.md" "primary_symbol must be the tradable underlying symbol"
check_file_contains "script inventory episode quality" "$PROJECT_DIR/docs/script_inventory.md" "check_episode_quality_contract.py"
echo "===== Episode Quality Contract ====="
if "$PY" "$PROJECT_DIR/scripts/journal/check_episode_quality_contract.py" --payload "$PROJECT_DIR/output/dashboard/latest/dashboard_payload_from_db.json" >/tmp/onejournal_episode_quality_check.out 2>/tmp/onejournal_episode_quality_check.err; then
  echo "OK   episode quality contract"
else
  echo "FAIL episode quality contract"
  cat /tmp/onejournal_episode_quality_check.out
  cat /tmp/onejournal_episode_quality_check.err
  fail_count=$((fail_count + 1))
fi

echo "===== Data contract ====="
check_path "docs/onejournal_data_contract_v1.md" "$PROJECT_DIR/docs/onejournal_data_contract_v1.md"
check_file_contains "data contract title" "$PROJECT_DIR/docs/onejournal_data_contract_v1.md" "OneJournal Data Contract v1"
check_file_contains "data contract asof" "$PROJECT_DIR/docs/onejournal_data_contract_v1.md" "--asof YYYY-MM-DD"
check_file_contains "data contract no auto-trade" "$PROJECT_DIR/docs/onejournal_data_contract_v1.md" "No auto-trade in v1."
check_path "docs/normalized_fills_odfs_contract.md" "$PROJECT_DIR/docs/normalized_fills_odfs_contract.md"
check_file_contains "normalized fills csv transport" "$PROJECT_DIR/docs/normalized_fills_odfs_contract.md" "CSV is an ingestion and transport format only"
check_file_contains "normalized fills duckdb truth" "$PROJECT_DIR/docs/normalized_fills_odfs_contract.md" "DuckDB normalized_fills is the imported fills source of truth"
check_file_contains "normalized fills import runs" "$PROJECT_DIR/docs/normalized_fills_odfs_contract.md" "Every import into DuckDB must create or update an import_runs row"
check_path "scripts/journal/check_import_run_audit.py" "$PROJECT_DIR/scripts/journal/check_import_run_audit.py"
check_path "docs/import_run_audit_contract.md" "$PROJECT_DIR/docs/import_run_audit_contract.md"
check_file_contains "import run audit truth" "$PROJECT_DIR/docs/import_run_audit_contract.md" "DuckDB import_runs is the import audit source of truth"
check_file_contains "import run audit linkage" "$PROJECT_DIR/docs/import_run_audit_contract.md" "every normalized_fills row must have import_run_id"
check_file_contains "script inventory import audit" "$PROJECT_DIR/docs/script_inventory.md" "check_import_run_audit.py"
echo "===== Import Run Audit Contract ====="
if "$PY" "$PROJECT_DIR/scripts/journal/check_import_run_audit.py" --db "$PROJECT_DIR/data/journal/onejournal.duckdb" >/tmp/onejournal_import_run_audit.out 2>/tmp/onejournal_import_run_audit.err; then
  echo "OK   import run audit contract"
else
  echo "FAIL import run audit contract"
  cat /tmp/onejournal_import_run_audit.out
  cat /tmp/onejournal_import_run_audit.err
  fail_count=$((fail_count + 1))
fi
check_file_contains "normalized fills no direct dashboard" "$PROJECT_DIR/docs/normalized_fills_odfs_contract.md" "broker CSV directly to dashboard"
check_path "docs/odfs_ingestion_folder_contract.md" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md"
check_path "data/raw/schwab" "$PROJECT_DIR/data/raw/schwab"
check_path "data/raw/ibkr" "$PROJECT_DIR/data/raw/ibkr"
check_path "data/raw/manual_imports" "$PROJECT_DIR/data/raw/manual_imports"
check_path "data/normalized/fills" "$PROJECT_DIR/data/normalized/fills"
check_path "data/audit/run_log" "$PROJECT_DIR/data/audit/run_log"
check_file_contains "odfs folder raw schwab" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md" "data/raw/schwab stores original Schwab files exactly as exported"
check_file_contains "odfs folder raw ibkr" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md" "data/raw/ibkr stores original IBKR files exactly as exported"
check_file_contains "odfs folder normalized fills" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md" "data/normalized/fills stores canonical OneJournal normalized fills"
check_file_contains "odfs folder no raw dashboard" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md" "Do not use raw broker CSV directly for dashboard payloads"
check_file_contains "odfs folder no raw episodes" "$PROJECT_DIR/docs/odfs_ingestion_folder_contract.md" "Do not import raw broker CSV directly into trade_episodes"
check_file_contains "operator phase i3 folder rule" "$PROJECT_DIR/docs/operator_quickstart.md" "Phase I3 ODFS folder rule"
check_file_contains "operator phase i1 ingestion rule" "$PROJECT_DIR/docs/operator_quickstart.md" "Phase I1 ODFS ingestion rule"
check_file_contains "data contract phase i1" "$PROJECT_DIR/docs/onejournal_data_contract_v1.md" "Phase I1 normalized fills ODFS rule"

echo
echo "===== Script inventory doc ====="
check_path "docs/script_inventory.md" "$PROJECT_DIR/docs/script_inventory.md"
check_file_contains "script inventory title" "$PROJECT_DIR/docs/script_inventory.md" "OneJournal Script Inventory"
check_file_contains "script inventory phase b source" "$PROJECT_DIR/docs/script_inventory.md" "Phase B source of truth: DuckDB manual_reviews"
check_file_contains "script inventory removal rule" "$PROJECT_DIR/docs/script_inventory.md" "A script can be removed only after the reference matrix shows zero production, baseline, documentation, and migration-safety references"
check_file_contains "script inventory build_dashboard_payload_from_db" "$PROJECT_DIR/docs/script_inventory.md" "build_dashboard_payload_from_db.py"
check_file_contains "script inventory check_dashboard_payload" "$PROJECT_DIR/docs/script_inventory.md" "check_dashboard_payload.py"
check_file_contains "script inventory check_journal_db" "$PROJECT_DIR/docs/script_inventory.md" "check_journal_db.py"
check_file_contains "script inventory check_manual_fills" "$PROJECT_DIR/docs/script_inventory.md" "check_manual_fills.py"
check_file_contains "script inventory check_strategy_classification" "$PROJECT_DIR/docs/script_inventory.md" "check_strategy_classification.py"
check_file_contains "script inventory check_trade_episodes" "$PROJECT_DIR/docs/script_inventory.md" "check_trade_episodes.py"
check_file_contains "script inventory compare_dashboard_payloads" "$PROJECT_DIR/docs/script_inventory.md" "compare_dashboard_payloads.py"
check_file_contains "script inventory import_journal_to_db" "$PROJECT_DIR/docs/script_inventory.md" "import_journal_to_db.py"
check_file_contains "import journal odfs asof cli" "$PROJECT_DIR/scripts/journal/import_journal_to_db.py" "--asof"
check_file_contains "import journal odfs file alias" "$PROJECT_DIR/scripts/journal/import_journal_to_db.py" "fills_alias"
check_file_contains "operator phase h0 import cli" "$PROJECT_DIR/docs/operator_quickstart.md" "Phase H0 ODFS Import CLI"
check_file_contains "operator phase h0 file alias" "$PROJECT_DIR/docs/operator_quickstart.md" "ODFS alias for"
check_file_contains "script inventory init_journal_db" "$PROJECT_DIR/docs/script_inventory.md" "init_journal_db.py"
check_file_contains "script inventory refresh_dashboard" "$PROJECT_DIR/docs/script_inventory.md" "refresh_dashboard.py"
check_file_contains "script inventory refresh_dashboard_db_transition" "$PROJECT_DIR/docs/script_inventory.md" "refresh_dashboard_db_transition.py"
check_file_contains "script inventory update_review_template" "$PROJECT_DIR/docs/script_inventory.md" "update_review_template.py"
check_file_contains "script inventory upsert_manual_review_to_db" "$PROJECT_DIR/docs/script_inventory.md" "upsert_manual_review_to_db.py"

echo

echo "===== ODFS folders ====="
for d in config data/raw data/normalized data/journal data/audit output/dashboard output/reports src/onejournal scripts/journal tests docs; do
  check_path "$d" "$PROJECT_DIR/$d"
done

echo

if [ "$fail_count" -eq 0 ]; then
  check_path "scripts/journal/check_db_dashboard_contract.py" "$PROJECT_DIR/scripts/journal/check_db_dashboard_contract.py"
check_path "docs/dashboard_db_contract.md" "$PROJECT_DIR/docs/dashboard_db_contract.md"
check_file_contains "dashboard db contract source" "$PROJECT_DIR/docs/dashboard_db_contract.md" "DuckDB table:"
check_file_contains "dashboard db contract payload" "$PROJECT_DIR/docs/dashboard_db_contract.md" "dashboard_payload_from_db.json"
check_file_contains "dashboard db contract save flow" "$PROJECT_DIR/docs/dashboard_db_contract.md" "Streamlit Save Review"

echo "===== DB Dashboard Contract ====="
if "$PY" "$PROJECT_DIR/scripts/journal/check_db_dashboard_contract.py" --asof 2026-06-02 --payload "$PROJECT_DIR/output/dashboard/latest/dashboard_payload_from_db.json" >/tmp/onejournal_db_dashboard_contract.out 2>&1
then
  echo "OK   db dashboard contract"
else
  echo "FAIL db dashboard contract"
  cat /tmp/onejournal_db_dashboard_contract.out
  fail_count=$((fail_count + 1))
fi

check_path "scripts/journal/check_save_review_flow.py" "$PROJECT_DIR/scripts/journal/check_save_review_flow.py"
check_path "docs/save_review_flow.md" "$PROJECT_DIR/docs/save_review_flow.md"
check_file_contains "save review flow source" "$PROJECT_DIR/docs/save_review_flow.md" "manual_reviews"
check_file_contains "save review flow temp db" "$PROJECT_DIR/docs/save_review_flow.md" "temporary validation DB"
check_file_contains "save review flow no broker" "$PROJECT_DIR/docs/save_review_flow.md" "No broker API call."

echo "===== Save Review Flow ====="
if "$PY" "$PROJECT_DIR/scripts/journal/check_save_review_flow.py" --asof 2026-06-02 --db "$PROJECT_DIR/data/journal/onejournal.duckdb" >/tmp/onejournal_save_review_flow.out 2>&1
then
  echo "OK   save review flow"
else
  echo "FAIL save review flow"
  cat /tmp/onejournal_save_review_flow.out
  fail_count=$((fail_count + 1))
fi
echo "PASS OneJournal baseline looks good."
  exit 0
else
  echo "FAIL OneJournal baseline check found $fail_count issue(s)."
  exit 1
fi
