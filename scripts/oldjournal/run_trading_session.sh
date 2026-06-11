#!/usr/bin/env bash
set -u

# ---------------------------------------------
# Trading session runner (poll + stream + ingest)
# Compatible with unified client.streamer_client (--service ...)
# ---------------------------------------------

DEBUG="${DEBUG:-0}"

ROTATE_MSGS="${ROTATE_MSGS:-30}"                  # max NDJSON output lines per capture (best-effort)
STREAM_TIMEOUT_SECS="${STREAM_TIMEOUT_SECS:-300}" # hard stop for each capture

POLL_SECS="${POLL_SECS:-60}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-60}"
export LOOKBACK_DAYS

PY="${PY:-python}"

ET_TZ="America/New_York"
SESSION_END_ET="${SESSION_END_ET:-20:05}"

# unified streamer service name
STREAM_SERVICE="${STREAM_SERVICE:-ACCT_ACTIVITY}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ---- make imports deterministic ----
# Always run from the tgps-project repo (not whatever directory you launched from)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$CODE_DIR" || exit 2
export PYTHONPATH="${CODE_DIR}:${PYTHONPATH:-}"

# DB in iCloud project (your current setup)
DB="${DB:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/TradersGPS/data/journal/tgps_trades.duckdb}"

# ------------------ DB mutex (prevents DuckDB lock collisions) ------------------
DB_LOCKFILE="${DB_LOCKFILE:-$HOME/.tgps_locks/tgps_trades.duckdb.lock}"
mkdir -p "$(dirname "$DB_LOCKFILE")"

db_lock_run() {
  # Usage: db_lock_run <command> [args...]
  "$PY" - "$DB_LOCKFILE" "$@" <<'PY'
import fcntl, os, subprocess, sys
lockfile = sys.argv[1]
cmd = sys.argv[2:]
os.makedirs(os.path.dirname(lockfile), exist_ok=True)
with open(lockfile, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)   # blocks until free
    raise SystemExit(subprocess.call(cmd))
PY
}
# ------------------ session setup ------------------

STREAM_DIR="${STREAM_DIR:-$CODE_DIR/data/schwab/stream}"
mkdir -p "$STREAM_DIR"

calc_window_dates() {
  "$PY" - <<PY
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
ET = ZoneInfo("${ET_TZ}")
lookback = int(os.environ.get("LOOKBACK_DAYS","60"))
today = datetime.now(ET).date()
frm = today - timedelta(days=lookback)
print(frm.isoformat(), today.isoformat())
PY
}

compute_target_end_et_iso() {
  "$PY" - <<PY
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
ET = ZoneInfo("${ET_TZ}")
hh, mm = map(int, "${SESSION_END_ET}".split(":"))
now = datetime.now(ET)
target = datetime.combine(now.date(), time(hh, mm), tzinfo=ET)
if now >= target:
    target = target + timedelta(days=1)
print(target.isoformat())
PY
}

should_stop_now() {
  "$PY" - <<PY
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("${ET_TZ}")
now = datetime.now(ET)
target = datetime.fromisoformat("${TARGET_END_ET_ISO}")
print("1" if now >= target else "0")
PY
}

cleanup() {
  log "[session] stopping..."
  if [ "${POLL_PID:-}" != "" ]; then
    kill "$POLL_PID" >/dev/null 2>&1 || true
    wait "$POLL_PID" >/dev/null 2>&1 || true
  fi
  log "[session] stopped."
}
trap cleanup INT TERM

log "[session] CODE_DIR=$CODE_DIR"
log "[session] DB=$DB"
log "[session] STREAM_DIR=$STREAM_DIR"
log "[session] ROTATE_MSGS=$ROTATE_MSGS | STREAM_TIMEOUT_SECS=$STREAM_TIMEOUT_SECS | POLL_SECS=$POLL_SECS | LOOKBACK_DAYS=$LOOKBACK_DAYS"

TARGET_END_ET_ISO="$(compute_target_end_et_iso)"
log "[session] SESSION_END_ET=$SESSION_END_ET | TARGET_END_ET_ISO=$TARGET_END_ET_ISO"

# Ensure we run from the tgps-project repo
cd "$CODE_DIR" || exit 1
export PYTHONPATH="$CODE_DIR:${PYTHONPATH:-}"
# ------------------ preflight ------------------

log "[session] preflight Schwab token..."
"$PY" -m client.schwab_admin preflight || { log "[session] preflight failed. stopping."; exit 2; }

# Ensure ingest script loads (do not fail session on schema bootstrap)
db_lock_run "$PY" -m scripts.journal.ingest_acct_activity --db "$DB" --file /dev/null >/dev/null 2>&1 || true


# ------------------ poll loop ------------------
poll_loop() {
  while true; do
    if [ "$(should_stop_now)" = "1" ]; then
      log "[poll] session end reached (ET ${SESSION_END_ET}). stopping poll loop."
      break
    fi

    read -r FROM_DATE TO_DATE < <(calc_window_dates)
    log "[poll] fetch_orders_live --from $FROM_DATE --to $TO_DATE"

    if [ "$DEBUG" != "0" ]; then
      db_lock_run "$PY" -m scripts.journal.fetch_orders_live --from "$FROM_DATE" --to "$TO_DATE" --debug || true
    else
      db_lock_run "$PY" -m scripts.journal.fetch_orders_live --from "$FROM_DATE" --to "$TO_DATE" >/dev/null 2>&1 || true
    fi

    sleep "$POLL_SECS"
  done
}

log "[session] starting poll loop in background..."
poll_loop &
POLL_PID=$!
log "[session] poll PID=$POLL_PID"

# ------------------ stream loop ------------------
log "[session] starting stream loop in foreground..."

while true; do
  if [ "$(should_stop_now)" = "1" ]; then
    log "[stream] session end reached (ET ${SESSION_END_ET}). stopping stream loop."
    break
  fi

  OUTFILE="$STREAM_DIR/acct_activity_$(date '+%Y%m%d_%H%M%S').ndjson"
  ERRFILE="${OUTFILE}.stderr"

  log "[stream] capture service=$STREAM_SERVICE timeout=${STREAM_TIMEOUT_SECS}s -> $(basename "$OUTFILE")"

  # Run streamer in background so we can enforce a hard timeout
  if [ "$DEBUG" != "0" ]; then
    "$PY" -m client.streamer_client \
      --service "$STREAM_SERVICE" \
      --ndjson \
      --max-msgs "$ROTATE_MSGS" \
      --debug \
      > "$OUTFILE" 2> "$ERRFILE" &
  else
    "$PY" -m client.streamer_client \
      --service "$STREAM_SERVICE" \
      --ndjson \
      --max-msgs "$ROTATE_MSGS" \
      > "$OUTFILE" 2> "$ERRFILE" &
  fi

  SPID=$!

  # wait up to STREAM_TIMEOUT_SECS, then kill if still running
  SECS="$STREAM_TIMEOUT_SECS"
  while kill -0 "$SPID" >/dev/null 2>&1; do
    if [ "$SECS" -le 0 ]; then
      kill "$SPID" >/dev/null 2>&1 || true
      break
    fi
    sleep 1
    SECS=$((SECS-1))
  done
  wait "$SPID" >/dev/null 2>&1 || true

  # If file is empty, skip ingest (and avoid piling up junk)
  if [ ! -s "$OUTFILE" ]; then
    log "[db] ingest skip (empty): $OUTFILE"
    rm -f "$OUTFILE" "$ERRFILE" >/dev/null 2>&1 || true
    continue
  fi

  # Ingest (never stop session if ingest fails)
  if [ "$DEBUG" != "0" ]; then
    log "[db] ingest: $(basename "$OUTFILE")"
    db_lock_run "$PY" -m scripts.journal.ingest_acct_activity --db "$DB" --file "$OUTFILE" --debug \
      || log "[db] ingest failed (continuing): $OUTFILE"
  else
    db_lock_run "$PY" -m scripts.journal.ingest_acct_activity --db "$DB" --file "$OUTFILE" >/dev/null 2>&1 || true
  fi
done

cleanup
exit 0
