#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/ideas_runner.py

Version: 0.1.3
Updated: 2026-01-15 (SGT)

Step 0.6 (Planner)
------------------
Reads the latest ideas Excel from cloud, applies global policy rules,
writes into the local ledger DuckDB (attached as catalog "ledger"), and exports
a SYSTEM queue workbook (do not edit).

System queue naming:
  <prefix>_sellput_queue_sys.xlsx

Queue editing is handled by:
  python -m scripts.tgps_user.queue_editor patch

CLI
---
python -m scripts.tgps_user.ideas_runner check
python -m scripts.tgps_user.ideas_runner plan
python -m scripts.tgps_user.ideas_runner plan --force-new-run
python -m scripts.tgps_user.ideas_runner plan --outdir "<path>"

Policy support
--------------
Supports BOTH rule shapes:

A) Expression rules (new):
   - code, when, status, why
   Example: when: "Open Interest < min_open_interest"

B) Field comparator rules (legacy):
   - code, field, op, value/value_from, status

Notes
-----
- Ledger is attached as catalog "ledger", schema is "lcl" ⇒ ledger.lcl.<table>
- Policy YAML may be either:
    * { modules: { sellput: {...} } }
    * { sellput: {...} }  (module at top-level)
- Reads ideas excel path from lcl.user.yml using any of:
    * ideas_source.latest.excel     (preferred)
    * ideas_source.latest_excel     (legacy)
    * ideas_source_compat.latest_excel
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd

try:
    import yaml  # type: ignore
except Exception as e:
    raise SystemExit(f"Missing dependency: pyyaml. Install it in tgps-env. Error: {e}")

SGT = timezone(timedelta(hours=8))

# Repo root bootstrap: <repo>/scripts/tgps_user/ideas_runner.py -> parents[2]
CODE_DIR = Path(__file__).resolve().parents[2]

DEFAULT_USER_YML = str(CODE_DIR / "tgps-user" / "config" / "lcl.user.yml")
DEFAULT_LEDGER_DB = str(CODE_DIR / "tgps-user" / "ledger" / "lcl.ledger.duckdb")
DEFAULT_OUTDIR = str(CODE_DIR / "tgps-user" / "output" / "sellput")

DEFAULT_MODULE = "sellput"
DEFAULT_SHEET = "Conservative"  # if your cloud excel keeps only one sheet, we’ll auto-pick the first


def _now_sgt() -> datetime:
    return datetime.now(SGT)


def _now_sgt_iso() -> str:
    return _now_sgt().isoformat(timespec="seconds")


def _fq_schema() -> str:
    return "ledger.lcl"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_yml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_cloud_path(cloud_root: str, rel_path: str) -> str:
    p = Path(os.path.expanduser(str(rel_path)))
    if p.is_absolute():
        return str(p)
    return str(Path(os.path.expanduser(str(cloud_root))) / str(rel_path).lstrip("/"))


def _attach_ledger(con: duckdb.DuckDBPyConnection, ledger_db: str) -> str:
    ledger_db = os.path.expanduser(ledger_db)
    Path(ledger_db).parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"ATTACH '{ledger_db}' AS ledger;")
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {_fq_schema()};")
    return ledger_db


def _ledger_has_table(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    r = con.execute(
        """
        select 1
        from information_schema.tables
        where table_catalog='ledger' and table_schema='lcl' and table_name=?
        limit 1
        """,
        [table],
    ).fetchone()
    return bool(r)


def _require_ledger_tables(con: duckdb.DuckDBPyConnection, tables: List[str]) -> None:
    missing = [t for t in tables if not _ledger_has_table(con, t)]
    if missing:
        raise SystemExit(
            "Ledger schema missing required tables: "
            + ", ".join(missing)
            + "\nRun: python -m scripts.tgps_user.init_ledger --check"
        )


def _get_latest_excel_rel(user_yml: Dict[str, Any]) -> str:
    ideas = user_yml.get("ideas_source") or {}
    if isinstance(ideas, dict):
        latest = ideas.get("latest") or {}
        if isinstance(latest, dict):
            v = str(latest.get("excel") or "").strip()
            if v:
                return v
        v = str(ideas.get("latest_excel") or "").strip()
        if v:
            return v

    compat = user_yml.get("ideas_source_compat") or {}
    if isinstance(compat, dict):
        v = str(compat.get("latest_excel") or "").strip()
        if v:
            return v

    raise SystemExit(
        "lcl.user.yml missing ideas excel path. Provide one of:\n"
        "  ideas_source.latest.excel\n"
        "  ideas_source.latest_excel\n"
        "  ideas_source_compat.latest_excel"
    )


def _get_module_policy(policy: Dict[str, Any], module: str) -> Dict[str, Any]:
    """Accepts either {modules:{<module>:{...}}} or {<module>:{...}}."""
    mod = (module or "").strip()
    if not mod:
        return {}

    mods = policy.get("modules")
    if isinstance(mods, dict) and isinstance(mods.get(mod), dict):
        return mods.get(mod) or {}

    if isinstance(policy.get(mod), dict):
        return policy.get(mod) or {}

    return {}


def _load_policy(user_yml: Dict[str, Any], *, module: str) -> Tuple[str, Dict[str, Any]]:
    pol_rel = (user_yml.get("policy_source") or {}).get("global_policy") or ""
    if not pol_rel:
        raise SystemExit("lcl.user.yml missing: policy_source.global_policy")

    cloud_root = (user_yml.get("ideas_source") or {}).get("cloud_root") or ""
    if not cloud_root:
        raise SystemExit("lcl.user.yml missing: ideas_source.cloud_root")

    policy_path = _resolve_cloud_path(cloud_root, pol_rel)
    if not os.path.exists(policy_path):
        raise SystemExit(f"Policy file not found: {policy_path}")

    pol = _read_yml(policy_path)
    mod_policy = _get_module_policy(pol, module)
    if not isinstance(mod_policy, dict) or not mod_policy:
        raise SystemExit(
            f"Module policy not found in {policy_path}. "
            f"Expected either top-level '{module}:' or 'modules.{module}'."
        )

    return policy_path, mod_policy


def _pick_sheet(excel_path: str, preferred: str) -> str:
    try:
        xl = pd.ExcelFile(excel_path, engine="openpyxl")
        sheets = xl.sheet_names
        if not sheets:
            raise SystemExit("Ideas Excel has no sheets.")
        if preferred in sheets:
            return preferred
        return sheets[0]
    except Exception as e:
        raise SystemExit(f"Unable to read Excel sheets: {excel_path} ({e})")


def _read_ideas_excel(excel_path: str, sheet: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        raise SystemExit(f"Failed reading ideas Excel: {excel_path} sheet={sheet} ({e})")


def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, float) and (pd.isna(x)):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def _as_date_iso(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    try:
        ts = pd.to_datetime(x, errors="coerce")
        if pd.isna(ts):
            return ""
        return ts.date().isoformat()
    except Exception:
        return ""


def _compute_mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    if bid < 0 or ask < 0:
        return None
    return (bid + ask) / 2.0


def _compute_spread_pct(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    mid = _compute_mid(bid, ask)
    if mid is None or mid <= 0:
        return None
    return (ask - bid) / mid


def _stable_row_hash(module: str, ticker: str, expiry_iso: str, strike_found: str) -> str:
    key = f"{module}|{ticker.strip().upper()}|{expiry_iso}|{strike_found.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _resolve_value_from(policy: Dict[str, Any], expr: str) -> Any:
    cur: Any = policy
    for part in str(expr).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _compare(op: str, left: Any, right: Any) -> bool:
    op = str(op).strip()
    if op in ("<", "<=", ">", ">="):
        lf = _as_float(left)
        rf = _as_float(right)
        if lf is None or rf is None:
            return False
        if op == "<":
            return lf < rf
        if op == "<=":
            return lf <= rf
        if op == ">":
            return lf > rf
        if op == ">=":
            return lf >= rf

    if op in ("==", "!="):
        return (left == right) if op == "==" else (left != right)

    return False


def _normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Map original column names to safe python identifiers for expression eval.
    Returns (df_safe, colmap) where colmap maps original -> safe.
    """
    colmap: Dict[str, str] = {}
    used = set()

    for c in df.columns:
        s = str(c).strip()
        safe = []
        for ch in s:
            safe.append(ch if ch.isalnum() else "_")
        safe_s = "".join(safe).strip("_")
        if not safe_s:
            safe_s = "col"
        if safe_s[0].isdigit():
            safe_s = "c_" + safe_s

        base = safe_s
        k = 2
        while safe_s in used:
            safe_s = f"{base}_{k}"
            k += 1

        used.add(safe_s)
        colmap[s] = safe_s

    df2 = df.copy()
    df2.columns = [colmap[str(c).strip()] for c in df.columns]
    return df2, colmap


def _rewrite_expr(expr: str, colmap: Dict[str, str]) -> str:
    """
    Replace occurrences of original column headers with safe identifiers.
    Longest-first to reduce partial collisions.
    """
    out = str(expr or "")
    pairs = sorted(colmap.items(), key=lambda kv: len(kv[0]), reverse=True)
    for orig, safe in pairs:
        out = out.replace(orig, safe)
    return out


_SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_eval(expr: str, env: Dict[str, Any]) -> bool:
    """
    Small eval surface:
      - no builtins
      - no implicit attribute access protections beyond that
    """
    expr = (expr or "").strip()
    if not expr:
        return False
    try:
        return bool(eval(expr, {"__builtins__": {}}, env))
    except Exception:
        return False


@dataclass
class EvalResult:
    status: str               # WATCH | REVIEW | SKIP | EXECUTE (if you ever enable it)
    rule_hits: List[str]      # rule codes
    metrics: Dict[str, Any]   # computed fields


def _eval_row(policy: Dict[str, Any], row_orig: Dict[str, Any], *, row_safe: Dict[str, Any], colmap: Dict[str, str]) -> EvalResult:
    rules = policy.get("rules") or []
    thresholds = policy.get("thresholds") or {}
    execution = policy.get("execution") or {}

    default_action = str(execution.get("default_action") or "WATCH").strip().upper()
    if default_action not in ("WATCH", "REVIEW", "SKIP", "EXECUTE"):
        default_action = "WATCH"

    # Compute bid/ask from ORIGINAL keys (most likely "Bid"/"Ask") then expose to env
    bid = _as_float(row_orig.get("Bid"))
    ask = _as_float(row_orig.get("Ask"))
    spread_pct = _compute_spread_pct(bid, ask)
    mid = _compute_mid(bid, ask)

    earnings_cfg = policy.get("earnings") or {}
    earnings_col = str(earnings_cfg.get("date_column") or "").strip()
    earnings_date_iso = _as_date_iso(row_orig.get(earnings_col)) if earnings_col else ""
    earnings_date_missing = True if not earnings_date_iso else False
    earnings_in_weeks: Optional[float] = None
    if earnings_date_iso:
        try:
            ed = datetime.fromisoformat(earnings_date_iso)
            delta_days = (ed.date() - _now_sgt().date()).days
            earnings_in_weeks = delta_days / 7.0
        except Exception:
            earnings_date_missing = True
            earnings_in_weeks = None

    # Build env for eval:
    # - safe columns
    # - thresholds
    # - computed helpers
    env: Dict[str, Any] = {}
    env.update(row_safe)
    env.update(thresholds)
    env["spread_pct"] = spread_pct
    env["bid"] = bid
    env["ask"] = ask
    env["mid"] = mid
    env["earnings_date_missing"] = bool(earnings_date_missing)
    env["earnings_in_weeks"] = earnings_in_weeks if earnings_in_weeks is not None else None

    final = default_action
    hits: List[str] = []

    def bump(new_status: str) -> None:
        nonlocal final
        new_status = (new_status or "").strip().upper()
        if new_status == "SKIP":
            final = "SKIP"
        elif new_status == "REVIEW" and final != "SKIP":
            final = "REVIEW"
        elif new_status == "EXECUTE" and final == "WATCH":
            final = "EXECUTE"
        elif new_status == "WATCH" and final not in ("SKIP", "REVIEW", "EXECUTE"):
            final = "WATCH"

    for r in rules:
        if not isinstance(r, dict):
            continue

        code = str(r.get("code") or "").strip() or "RULE"
        status = str(r.get("status") or "").strip().upper() or "REVIEW"

        # --- Shape A: expression rule: {when: "..."}
        if "when" in r:
            when = str(r.get("when") or "").strip()
            if not when:
                continue
            when_safe = _rewrite_expr(when, colmap)
            if _safe_eval(when_safe, env):
                hits.append(code)
                bump(status)
            continue

        # --- Shape B: legacy comparator: {field, op, value/value_from}
        field = str(r.get("field") or "").strip()
        op = str(r.get("op") or "").strip()
        if not field or not op:
            continue

        # map original field to safe if it's a column header; otherwise allow computed names
        field_safe = colmap.get(field, field)
        # prevent weird eval keys; direct lookup only
        if not _SAFE_NAME_RE.match(field_safe):
            continue

        left = env.get(field_safe)

        if "value_from" in r:
            right = _resolve_value_from(policy, str(r.get("value_from")))
        else:
            right = r.get("value")

        # guard earnings if missing
        if field_safe == "earnings_in_weeks" and env.get("earnings_in_weeks") is None:
            continue

        if _compare(op, left, right):
            hits.append(code)
            bump(status)

    metrics = {
        "spread_pct": spread_pct,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "earnings_date_missing": bool(earnings_date_missing),
        "earnings_in_weeks": earnings_in_weeks,
    }
    return EvalResult(status=final, rule_hits=hits, metrics=metrics)


def _run_id() -> str:
    return _now_sgt().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex()


def cmd_check(args: argparse.Namespace) -> None:
    user_yml_path = os.path.expanduser(args.user_yml)
    if not os.path.exists(user_yml_path):
        raise SystemExit(f"user_yml not found: {user_yml_path}")
    user_yml = _read_yml(user_yml_path)

    module = str(args.module or "").strip()
    if not module:
        raise SystemExit("module is empty")

    policy_path, mod_policy = _load_policy(user_yml, module=module)

    cloud_root = (user_yml.get("ideas_source") or {}).get("cloud_root") or ""
    latest_excel_rel = _get_latest_excel_rel(user_yml)
    if not cloud_root or not latest_excel_rel:
        raise SystemExit("lcl.user.yml missing ideas_source.cloud_root or ideas_source latest excel path")

    excel_path = _resolve_cloud_path(cloud_root, latest_excel_rel)
    if not os.path.exists(excel_path):
        raise SystemExit(f"Ideas Excel not found: {excel_path}")

    con = duckdb.connect(":memory:")
    try:
        _attach_ledger(con, args.ledger_db)
        _require_ledger_tables(con, ["policy_runs", "policy_row_results"])
    finally:
        con.close()

    sheet = args.sheet or _pick_sheet(excel_path, DEFAULT_SHEET)
    df = _read_ideas_excel(excel_path, sheet)

    required = mod_policy.get("required_columns") or []
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns in ideas Excel: {missing}")

    print(f"[ideas_runner] user_yml: {user_yml_path}")
    print(f"[ideas_runner] module: {module}")
    print(f"[ideas_runner] policy_yml: {policy_path}")
    print(f"[ideas_runner] ideas_excel: {excel_path}")
    print(f"[ideas_runner] sheet: {sheet}")
    print(f"[ideas_runner] rows: {len(df)}")
    print(f"[ideas_runner] required_columns ok: {len(required)}")
    print("[ideas_runner] OK")


def _insert_policy_run(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    module: str,
    source_path: str,
    source_sha256: str,
    source_mtime: str,
    policy_path: str,
    policy_sha256: str,
) -> None:
    con.execute(
        f"""
        INSERT INTO {_fq_schema()}.policy_runs(
          run_id, module, source_path, source_sha256, source_mtime,
          policy_path, policy_sha256, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            module,
            source_path,
            source_sha256,
            source_mtime,
            policy_path,
            policy_sha256,
            _now_sgt_iso(),
        ],
    )


def _find_existing_run(
    con: duckdb.DuckDBPyConnection,
    *,
    module: str,
    source_sha256: str,
    policy_sha256: str,
) -> Optional[str]:
    r = con.execute(
        f"""
        SELECT run_id
        FROM {_fq_schema()}.policy_runs
        WHERE module=? AND source_sha256=? AND policy_sha256=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [module, source_sha256, policy_sha256],
    ).fetchone()
    return str(r[0]) if r and r[0] else None


def _load_run_results_map(con: duckdb.DuckDBPyConnection, run_id: str) -> Dict[str, Tuple[str, str, str]]:
    rows = con.execute(
        f"""
        SELECT row_hash, status, rule_hits_json, metrics_json
        FROM {_fq_schema()}.policy_row_results
        WHERE run_id=?
        """,
        [run_id],
    ).fetchall()
    out: Dict[str, Tuple[str, str, str]] = {}
    for rh, st, hits, metrics in rows:
        out[str(rh)] = (str(st), str(hits), str(metrics))
    return out


def _insert_row_results(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    module: str,
    rows: List[Dict[str, Any]],
) -> None:
    uniq = {}
    for r in rows:
        uniq[r["row_hash"]] = r
    rows = list(uniq.values())

    schema = _fq_schema()
    for r in rows:
        con.execute(
            f"""
            INSERT INTO {schema}.policy_row_results(
              run_id, row_hash, module, ticker, expiry, strike_found,
              status, rule_hits_json, metrics_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                r.get("row_hash"),
                module,
                r.get("Ticker", ""),
                r.get("Expiry", ""),
                r.get("Strike Found", ""),
                r.get("policy_status"),
                r.get("rule_hits_json"),
                r.get("metrics_json"),
                _now_sgt_iso(),
            ],
        )


def _export_queue_excel(df: pd.DataFrame, out_path: str) -> None:
    """
    Export ONLY one sheet: ALL
    (You can re-add REVIEW/WATCH/SKIP later if/when the UI needs it.)
    """
    out_dir = Path(out_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="ALL")


def cmd_plan(args: argparse.Namespace) -> None:
    user_yml_path = os.path.expanduser(args.user_yml)
    if not os.path.exists(user_yml_path):
        raise SystemExit(f"user_yml not found: {user_yml_path}")

    user_yml = _read_yml(user_yml_path)
    module = args.module

    policy_path, mod_policy = _load_policy(user_yml, module=module)
    policy_sha = _sha256_file(policy_path)

    cloud_root = (user_yml.get("ideas_source") or {}).get("cloud_root") or ""
    latest_excel_rel = _get_latest_excel_rel(user_yml)
    if not cloud_root or not latest_excel_rel:
        raise SystemExit("lcl.user.yml missing ideas_source.cloud_root or ideas_source latest excel path")

    excel_path = _resolve_cloud_path(cloud_root, latest_excel_rel)
    if not os.path.exists(excel_path):
        raise SystemExit(f"Ideas Excel not found: {excel_path}")

    source_sha = _sha256_file(excel_path)
    mtime = datetime.fromtimestamp(os.path.getmtime(excel_path), tz=SGT).isoformat()

    sheet = args.sheet or _pick_sheet(excel_path, DEFAULT_SHEET)

    df = _read_ideas_excel(excel_path, sheet)
    required = mod_policy.get("required_columns") or []
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns in ideas Excel: {missing}")

    # Build safe df for expression eval, but keep original df for output
    df_safe, colmap = _normalize_columns(df)

    df["Ticker"] = df["Ticker"].apply(_as_str).str.upper()
    df["Expiry"] = df["Expiry"].apply(_as_date_iso)
    df["Strike Found"] = df["Strike Found"].apply(_as_str)

    con = duckdb.connect(":memory:")
    try:
        _attach_ledger(con, args.ledger_db)
        _require_ledger_tables(con, ["policy_runs", "policy_row_results"])

        existing_run: Optional[str] = None
        if not args.force_new_run:
            existing_run = _find_existing_run(
                con,
                module=module,
                source_sha256=source_sha,
                policy_sha256=policy_sha,
            )

        if existing_run:
            run_id = existing_run
            results_map = _load_run_results_map(con, run_id)
            print(f"[ideas_runner] reuse_run_id: {run_id} (same source_sha + policy_sha)")

            row_hashes: List[str] = []
            for _, r in df.iterrows():
                rh = _stable_row_hash(
                    module,
                    _as_str(r.get("Ticker")),
                    _as_str(r.get("Expiry")),
                    _as_str(r.get("Strike Found")),
                )
                row_hashes.append(rh)

            df["row_hash"] = row_hashes
            df["policy_status"] = "WATCH"
            df["rule_hits"] = ""
            df["spread_pct"] = None

            missing_idx: List[int] = []
            for idx, rh in zip(df.index, row_hashes):
                got = results_map.get(rh)
                if not got:
                    missing_idx.append(idx)
                    continue

                st, hits_json, metrics_json = got
                df.at[idx, "policy_status"] = st

                try:
                    hits = json.loads(hits_json)
                    df.at[idx, "rule_hits"] = ",".join([str(x) for x in hits]) if isinstance(hits, list) else str(hits)
                except Exception:
                    df.at[idx, "rule_hits"] = hits_json

                try:
                    metrics = json.loads(metrics_json)
                    df.at[idx, "spread_pct"] = metrics.get("spread_pct")
                except Exception:
                    pass

            if missing_idx:
                print(
                    f"[ideas_runner] warning: {len(missing_idx)} rows missing stored results; "
                    "will evaluate them now (no ledger insert)."
                )
                for idx in missing_idx:
                    r_orig = df.loc[idx].to_dict()
                    r_safe = df_safe.loc[idx].to_dict()
                    ev = _eval_row(mod_policy, r_orig, row_safe=r_safe, colmap=colmap)
                    df.at[idx, "policy_status"] = ev.status
                    df.at[idx, "rule_hits"] = ",".join(ev.rule_hits)
                    df.at[idx, "spread_pct"] = ev.metrics.get("spread_pct")

        else:
            run_id = _run_id()
            _insert_policy_run(
                con,
                run_id=run_id,
                module=module,
                source_path=excel_path,
                source_sha256=source_sha,
                source_mtime=mtime,
                policy_path=policy_path,
                policy_sha256=policy_sha,
            )
            print(f"[ideas_runner] new_run_id: {run_id}")

            rows_to_insert: List[Dict[str, Any]] = []

            row_hashes: List[str] = []
            statuses: List[str] = []
            hits_list: List[str] = []
            spread_list: List[Optional[float]] = []

            for idx, r in df.iterrows():
                ticker = _as_str(r.get("Ticker")).upper()
                expiry_iso = _as_str(r.get("Expiry"))
                strike_found = _as_str(r.get("Strike Found"))
                rh = _stable_row_hash(module, ticker, expiry_iso, strike_found)

                r_orig = r.to_dict()
                r_safe = df_safe.loc[idx].to_dict()

                ev = _eval_row(mod_policy, r_orig, row_safe=r_safe, colmap=colmap)

                row_hashes.append(rh)
                statuses.append(ev.status)
                hits_list.append(",".join(ev.rule_hits))
                spread_list.append(ev.metrics.get("spread_pct"))

                rows_to_insert.append(
                    {
                        "row_hash": rh,
                        "Ticker": ticker,
                        "Expiry": expiry_iso,
                        "Strike Found": strike_found,
                        "policy_status": ev.status,
                        "rule_hits_json": json.dumps(ev.rule_hits, ensure_ascii=False),
                        "metrics_json": json.dumps(ev.metrics, ensure_ascii=False),
                    }
                )

            df["row_hash"] = row_hashes
            df["policy_status"] = statuses
            df["rule_hits"] = hits_list
            df["spread_pct"] = spread_list

            _insert_row_results(con, run_id=run_id, module=module, rows=rows_to_insert)

        outdir = os.path.expanduser(args.outdir or DEFAULT_OUTDIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)

        prefix = f"{_now_sgt().strftime('%Y-%m-%d_%H%M%S')}_{module}"
        out_path = str(Path(outdir) / f"{prefix}_sellput_queue_sys.xlsx")
        _export_queue_excel(df, out_path)

        counts = df["policy_status"].value_counts(dropna=False).to_dict()
        print(f"[ideas_runner] wrote: {out_path}")
        print(f"[ideas_runner] counts: {counts}")

    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TGPS Ideas Runner (Planner) - policy queue + ledger")
    ap.add_argument("--user-yml", default=DEFAULT_USER_YML, help=f"User config yml (default: {DEFAULT_USER_YML})")
    ap.add_argument("--ledger-db", default=DEFAULT_LEDGER_DB, help=f"Ledger db (default: {DEFAULT_LEDGER_DB})")
    ap.add_argument("--module", default=DEFAULT_MODULE, help=f"Module name (default: {DEFAULT_MODULE})")
    ap.add_argument("--sheet", default="", help="Excel sheet name (default: auto-pick Conservative/first sheet)")
    ap.add_argument("--outdir", default="", help=f"Output directory (default: {DEFAULT_OUTDIR})")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="Validate config/policy/ledger and required columns")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("plan", help="Apply policy -> write queue results to ledger -> export SYSTEM queue workbook")
    p.add_argument("--force-new-run", action="store_true", help="Force a new policy_run even if source/policy sha matches")
    p.set_defaults(func=cmd_plan)

    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.module = str(args.module or DEFAULT_MODULE).strip()

    try:
        args.func(args)
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
