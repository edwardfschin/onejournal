#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/sync_ideas.py

Version: 0.1.2
Updated: 2026-01-14 (SGT)

Purpose
-------
Sync latest ideas Excel from cloud into the local ledger, safely:
- Reads lcl.user.yml for the cloud path to latest_sellput_ideas_user.xlsx
- Generates a stable idea_id per contract key (module+ticker+expiry+strike_found)
- Appends a snapshot to ledger.lcl.idea_snapshots
- Upserts dedupe state into ledger.lcl.ideas_seen (first_seen/last_seen/seen_count)

Hard-fail guarantees (v0.1.2)
-----------------------------
- If the ideas Excel is empty -> FAIL (non-zero exit)
- If no usable idea rows after cleaning -> FAIL (non-zero exit)

Optional freshness guard
------------------------
--require-new
  Fail if source_sha256 is unchanged vs the last synced snapshot for the same module.

Transaction safety
-------------------
- Inserts + upserts are wrapped in a single transaction (BEGIN/COMMIT, ROLLBACK on error)

Notes (DuckDB v1.4.2)
---------------------
We ATTACH the ledger DB as catalog "ledger" and use schema "lcl":
  ledger.lcl.<table>

Usage
-----
python -m scripts.tgps_user.sync_ideas check
python -m scripts.tgps_user.sync_ideas run
python -m scripts.tgps_user.sync_ideas run --require-new
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd

# --- Repo bootstrap ---
CODE_DIR = Path(__file__).resolve().parents[2]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

try:
    from common.paths import env  # type: ignore
except Exception:
    env = None  # fallback: use cwd-based defaults

SGT = timezone(timedelta(hours=8))

CATALOG = "ledger"
SCHEMA = "lcl"


def _fq(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


def _now_sgt() -> datetime:
    return datetime.now(SGT)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_abs(p: str) -> bool:
    p = (p or "").strip()
    if not p:
        return False
    return p.startswith("/") or p.startswith("~")


def _safe_attach_path(p: str) -> str:
    # Escape single quotes for SQL string literal
    return p.replace("'", "''")


def _connect_attached(db_path: str) -> duckdb.DuckDBPyConnection:
    """
    Attach the ledger file as catalog 'ledger' so we can use ledger.lcl.<table>.
    """
    db_path = os.path.expanduser(db_path)
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{_safe_attach_path(db_path)}' AS {CATALOG};")
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA};")
    return con


def _yaml_load(path: str) -> Dict[str, Any]:
    path = os.path.expanduser(path)
    try:
        import yaml  # type: ignore
    except Exception:
        raise SystemExit("Missing dependency: pyyaml. Install with: pip install pyyaml")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Config is not a YAML mapping: {path}")
    return data


def _default_paths() -> Tuple[str, str]:
    """
    Returns: (default_config_path, default_db_path)
    """
    if env and isinstance(env, dict) and env.get("project_dir"):
        proj = str(env["project_dir"])
    else:
        proj = str(CODE_DIR)

    cfg = os.path.join(proj, "tgps-user", "config", "lcl.user.yml")
    db = os.path.join(proj, "tgps-user", "ledger", "lcl.ledger.duckdb")
    return cfg, db


def _resolve_source_excel(cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Returns: (module, excel_path, sheet_name)
    """
    ideas = cfg.get("ideas_source") or {}
    if not isinstance(ideas, dict):
        raise SystemExit("ideas_source must be a mapping in lcl.user.yml")

    module = str(ideas.get("module") or "sellput").strip() or "sellput"
    cloud_root = str(ideas.get("cloud_root") or "").strip()
    latest_excel = str(ideas.get("latest_excel") or "").strip()
    sheet = str(ideas.get("sheet") or "").strip()

    if not latest_excel:
        raise SystemExit("ideas_source.latest_excel is required (path to latest_sellput_ideas_user.xlsx)")

    if _is_abs(latest_excel):
        excel_path = os.path.expanduser(latest_excel)
    else:
        if not cloud_root:
            raise SystemExit("ideas_source.cloud_root is required when latest_excel is relative")
        excel_path = os.path.join(os.path.expanduser(cloud_root), latest_excel)

    if not os.path.exists(excel_path):
        raise SystemExit(f"Latest ideas Excel not found: {excel_path}")

    return module, excel_path, sheet


def _read_ideas_excel(excel_path: str, sheet: str) -> pd.DataFrame:
    # If sheet blank, pandas reads first sheet by default
    df = pd.read_excel(excel_path, sheet_name=(sheet if sheet else 0), engine="openpyxl")
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _as_date(x: Any) -> Optional[str]:
    if pd.isna(x):
        return None
    try:
        d = pd.to_datetime(x).date()
        return d.isoformat()
    except Exception:
        return None


def _as_float(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    try:
        return float(s)
    except Exception:
        return None


def _as_int(v: Any) -> Optional[int]:
    f = _as_float(v)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _idea_key(module: str, ticker: str, expiry_iso: str, strike_found: Any) -> str:
    """
    Stable across refreshes:
      module + ticker + expiry + strike_found
    We intentionally exclude DTE/Underlying/ROI because they change daily.
    """
    t = (ticker or "").strip().upper()
    e = (expiry_iso or "").strip()

    sf = _as_float(strike_found)
    if sf is None:
        sf_s = str(strike_found).strip()
    else:
        sf_s = f"{sf:.4f}"

    return f"{module}|SELL_PUT|{t}|{e}|{sf_s}"


def _idea_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_fq("idea_snapshots")} (
          snapshot_at TIMESTAMP,
          module VARCHAR,
          idea_id VARCHAR,
          idea_key VARCHAR,

          ticker VARCHAR,
          expiry DATE,
          strike_found DOUBLE,

          -- typed columns (current sellput module schema)
          win_rate DOUBLE,
          start_md VARCHAR,
          end_md VARCHAR,
          days_left_in_trade BIGINT,
          ideal_strike DOUBLE,
          max_drawdown DOUBLE,
          underlying DOUBLE,
          annualised_simple DOUBLE,
          mos DOUBLE,
          open_interest BIGINT,
          dte BIGINT,
          last DOUBLE,
          bid DOUBLE,
          ask DOUBLE,
          mid DOUBLE,
          delta DOUBLE,
          beta_3m DOUBLE,
          implied_vol DOUBLE,

          -- provenance
          source_path VARCHAR,
          source_sha256 VARCHAR,
          source_mtime TIMESTAMP,

          -- raw for forward-compat when columns evolve
          row_json JSON
        );
        """
    )

    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_fq("ideas_seen")} (
          idea_id VARCHAR PRIMARY KEY,
          module VARCHAR,
          idea_key VARCHAR,
          ticker VARCHAR,
          expiry DATE,
          strike_found DOUBLE,
          first_seen_at TIMESTAMP,
          last_seen_at TIMESTAMP,
          seen_count BIGINT,
          last_source_path VARCHAR
        );
        """
    )

    con.execute(
        f"""
        CREATE VIEW IF NOT EXISTS {_fq("v_ideas_latest")} AS
        SELECT s.*
        FROM {_fq("idea_snapshots")} s
        QUALIFY ROW_NUMBER() OVER (PARTITION BY idea_id ORDER BY snapshot_at DESC) = 1;
        """
    )


def _table_columns(con: duckdb.DuckDBPyConnection, fq_table: str) -> List[str]:
    parts = fq_table.split(".")
    if len(parts) != 3:
        raise SystemExit(f"Expected fully qualified table name, got: {fq_table}")
    catalog, schema, name = parts
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog=? AND table_schema=? AND table_name=?
        ORDER BY ordinal_position
        """,
        [catalog, schema, name],
    ).fetchall()
    return [str(r[0]) for r in rows]


def _latest_source_sha_for_module(con: duckdb.DuckDBPyConnection, module: str) -> Optional[str]:
    try:
        r = con.execute(
            f"""
            SELECT source_sha256
            FROM {_fq("idea_snapshots")}
            WHERE module=?
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            [module],
        ).fetchone()
        if not r or not r[0]:
            return None
        return str(r[0])
    except Exception:
        return None


def _upsert_ideas_seen(
    con: duckdb.DuckDBPyConnection,
    *,
    now_ts: datetime,
    rows: List[Dict[str, Any]],
) -> Tuple[int, int]:
    fq_seen = _fq("ideas_seen")
    cols = set(_table_columns(con, fq_seen))

    new_n = 0
    upd_n = 0

    for r in rows:
        idea_id = r["idea_id"]
        exists = con.execute(f"SELECT 1 FROM {fq_seen} WHERE idea_id=? LIMIT 1", [idea_id]).fetchone()
        if not exists:
            new_n += 1
            payload = {
                "idea_id": idea_id,
                "module": r.get("module"),
                "idea_key": r.get("idea_key"),
                "ticker": r.get("ticker"),
                "expiry": r.get("expiry"),
                "strike_found": r.get("strike_found"),
                "first_seen_at": now_ts,
                "last_seen_at": now_ts,
                "seen_count": 1,
                "last_source_path": r.get("source_path"),
            }
            ins_cols = [c for c in payload.keys() if c in cols]
            ins_vals = [payload[c] for c in ins_cols]
            placeholders = ",".join(["?"] * len(ins_cols))
            con.execute(
                f"INSERT INTO {fq_seen} ({','.join(ins_cols)}) VALUES ({placeholders})",
                ins_vals,
            )
        else:
            upd_n += 1
            sets: List[str] = []
            params: List[Any] = []

            if "last_seen_at" in cols:
                sets.append("last_seen_at=?")
                params.append(now_ts)
            if "seen_count" in cols:
                sets.append("seen_count=COALESCE(seen_count,0)+1")
            if "last_source_path" in cols:
                sets.append("last_source_path=?")
                params.append(r.get("source_path"))

            if sets:
                params.append(idea_id)
                con.execute(f"UPDATE {fq_seen} SET {', '.join(sets)} WHERE idea_id=?", params)

    return new_n, upd_n


def _insert_snapshots(con: duckdb.DuckDBPyConnection, snapshot_rows: List[Dict[str, Any]]) -> int:
    fq_snap = _fq("idea_snapshots")
    cols = _table_columns(con, fq_snap)

    ins_cols = [c for c in cols if c in snapshot_rows[0].keys()]
    placeholders = ",".join(["?"] * len(ins_cols))
    sql = f"INSERT INTO {fq_snap} ({','.join(ins_cols)}) VALUES ({placeholders})"

    params_list: List[List[Any]] = []
    for r in snapshot_rows:
        params_list.append([r.get(c) for c in ins_cols])

    con.executemany(sql, params_list)
    return len(snapshot_rows)


def cmd_check(args: argparse.Namespace) -> None:
    cfg = _yaml_load(args.config)
    module, excel_path, sheet = _resolve_source_excel(cfg)

    print(f"[sync_ideas] module: {module}")
    print(f"[sync_ideas] source_excel: {excel_path}")
    if sheet:
        print(f"[sync_ideas] sheet: {sheet}")

    con = _connect_attached(args.db)
    try:
        _ensure_tables(con)
        n_seen = con.execute(f"SELECT COUNT(*) FROM {_fq('ideas_seen')}").fetchone()[0]
        n_snap = con.execute(f"SELECT COUNT(*) FROM {_fq('idea_snapshots')}").fetchone()[0]
        print(f"[sync_ideas] ledger tables ok: ideas_seen={n_seen} idea_snapshots={n_snap}")
    finally:
        con.close()


def cmd_run(args: argparse.Namespace) -> None:
    cfg = _yaml_load(args.config)
    module, excel_path, sheet = _resolve_source_excel(cfg)

    df = _read_ideas_excel(excel_path, sheet)
    if df.empty:
        raise SystemExit("❌ [sync_ideas] Ideas Excel is empty (or wrong sheet). Refusing to proceed.")

    # Required columns for stable IDs
    required = ["Ticker", "Expiry", "Strike Found"]
    missing = [x for x in required if x not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns in ideas Excel: {missing}")

    now_ts = _now_sgt()

    st = os.stat(excel_path)
    src_mtime = datetime.fromtimestamp(st.st_mtime, tz=SGT)
    src_sha = _sha256_file(excel_path)

    # Optional freshness guard: fail if unchanged vs last snapshot for module
    if args.require_new:
        con_chk = _connect_attached(args.db)
        try:
            _ensure_tables(con_chk)
            last_sha = _latest_source_sha_for_module(con_chk, module)
        finally:
            con_chk.close()

        if last_sha and last_sha == src_sha:
            raise SystemExit(
                f"❌ [sync_ideas] --require-new: source_sha256 unchanged for module={module}. "
                "Cloud file may not be updated yet."
            )

    snapshot_rows: List[Dict[str, Any]] = []
    seen_rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        ticker = str(row.get("Ticker") or "").strip().upper()
        expiry_iso = _as_date(row.get("Expiry"))
        if not ticker or not expiry_iso:
            continue

        strike_found_raw = row.get("Strike Found")
        strike_found = _as_float(strike_found_raw)
        if strike_found is None:
            continue

        key = _idea_key(module, ticker, expiry_iso, strike_found)
        iid = _idea_id(key)

        snap: Dict[str, Any] = {
            "snapshot_at": now_ts,
            "module": module,
            "idea_id": iid,
            "idea_key": key,
            "ticker": ticker,
            "expiry": expiry_iso,
            "strike_found": strike_found,
            "win_rate": _as_float(row.get("Win Rate (%)")),
            "start_md": None if pd.isna(row.get("Start")) else str(row.get("Start")),
            "end_md": None if pd.isna(row.get("End")) else str(row.get("End")),
            "days_left_in_trade": _as_int(row.get("Days Left in Trade")),
            "ideal_strike": _as_float(row.get("Ideal Strike")),
            "max_drawdown": _as_float(row.get("Max Drawdown")),
            "underlying": _as_float(row.get("Underlying")),
            "annualised_simple": _as_float(row.get("Annualised Simple (%)")),
            "mos": _as_float(row.get("MOS (%)")),
            "open_interest": _as_int(row.get("Open Interest")),
            "dte": _as_int(row.get("DTE")),
            "last": _as_float(row.get("Last")),
            "bid": _as_float(row.get("Bid")),
            "ask": _as_float(row.get("Ask")),
            "mid": _as_float(row.get("Mid")),
            "delta": _as_float(row.get("Delta")),
            "beta_3m": _as_float(row.get("Beta (3m)")),
            "implied_vol": _as_float(row.get("Implied Volatility")),
            "source_path": excel_path,
            "source_sha256": src_sha,
            "source_mtime": src_mtime,
            "row_json": row.to_json(),
        }
        snapshot_rows.append(snap)

        seen_rows.append(
            dict(
                idea_id=iid,
                module=module,
                idea_key=key,
                ticker=ticker,
                expiry=expiry_iso,
                strike_found=strike_found,
                source_path=excel_path,
            )
        )

    if not snapshot_rows:
        raise SystemExit(
            "❌ [sync_ideas] No usable idea rows after cleaning. "
            "Check Ticker/Expiry/Strike Found formats and the selected sheet."
        )

    con = _connect_attached(args.db)
    try:
        _ensure_tables(con)

        # ---- Transaction wrapper ----
        con.execute("BEGIN TRANSACTION;")
        try:
            inserted = _insert_snapshots(con, snapshot_rows)
            new_n, upd_n = _upsert_ideas_seen(con, now_ts=now_ts, rows=seen_rows)
            con.execute("COMMIT;")
        except Exception:
            try:
                con.execute("ROLLBACK;")
            except Exception:
                pass
            raise

        print(f"[sync_ideas] module: {module}")
        print(f"[sync_ideas] source_excel: {excel_path}")
        print(f"[sync_ideas] source_sha256: {src_sha[:12]}…  mtime={src_mtime.isoformat()}")
        print(f"[sync_ideas] rows_in_excel: {len(df)}")
        print(f"[sync_ideas] snapshots_inserted: {inserted}")
        print(f"[sync_ideas] ideas_seen: new={new_n} updated={upd_n}")

    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    default_cfg, default_db = _default_paths()

    ap = argparse.ArgumentParser(description="TGPS User: Sync ideas into local ledger")
    ap.add_argument("--config", default=default_cfg, help=f"Path to lcl.user.yml (default: {default_cfg})")
    ap.add_argument("--db", default=default_db, help=f"Path to lcl.ledger.duckdb (default: {default_db})")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="Validate config + ledger tables exist")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="Sync latest ideas Excel -> local ledger")
    p.add_argument(
        "--require-new",
        action="store_true",
        help="Fail if source_sha256 is unchanged vs last synced snapshot for the same module.",
    )
    p.set_defaults(func=cmd_run)

    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
