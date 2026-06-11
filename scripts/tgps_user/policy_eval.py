#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/policy_eval.py

Version: 0.1.1
Updated: 2026-01-10 (SGT)

Purpose
-------
Evaluate a module policy (cloud) against the latest synced ideas (cloud Excel),
then output:
- full evaluated workbook (all rows + flags + action)
- optional "review-only" workbook (REVIEW/SKIP only)

Key points
----------
- Accepts policy YAML in either shape:
    A) { modules: { sellput: {...} } }
    B) { sellput: {...} }   (module at top level)
- --only-review is now a RUN-subcommand flag:
    python -m scripts.tgps_user.policy_eval run --only-review
"""

from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml


SGT = timezone(timedelta(hours=8))


# ----------------------------
# Helpers
# ----------------------------

def _now_sgt_iso() -> str:
    return datetime.now(SGT).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"YAML not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"YAML must parse to a mapping/dict: {path}")
    return data


def _get_module_policy(policy: Dict[str, Any], module: str) -> Dict[str, Any]:
    """Return the module policy dict.

    Accepts two shapes:
      A) { "modules": { "<module>": { ... } } }
      B) { "<module>": { ... } }   (module at top level)
    """
    mod = (module or "").strip()
    if not mod:
        return {}

    mods = policy.get("modules")
    if isinstance(mods, dict) and isinstance(mods.get(mod), dict):
        return mods.get(mod) or {}

    if isinstance(policy.get(mod), dict):
        return policy.get(mod) or {}

    return {}


def _user_root(user_yml: Path) -> Path:
    # tgps-user/config/lcl.user.yml -> tgps-user
    return user_yml.resolve().parents[1]


def _resolve_cloud_path(user_cfg: Dict[str, Any], rel: str) -> Path:
    cloud_root = (user_cfg.get("ideas_source") or {}).get("cloud_root") or ""
    if not cloud_root:
        raise SystemExit("lcl.user.yml missing ideas_source.cloud_root")
    base = Path(os.path.expanduser(cloud_root))
    return (base / rel).resolve()


def _read_excel_rows(path: Path, sheet: Optional[str]) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"Ideas Excel not found: {path}")
    return pd.read_excel(path, sheet_name=sheet or 0, engine="openpyxl")


def _normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Map user column names to safe python identifiers for expression eval.
    Returns (df2, colmap) where colmap maps original -> safe.
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
        # dedupe
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


def _spread_pct(bid: Any, ask: Any) -> Optional[float]:
    try:
        b = float(bid)
        a = float(ask)
    except Exception:
        return None
    if a <= 0:
        return None
    return (a - b) / a


def _parse_date(x: Any) -> Optional[datetime]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, datetime):
        return x
    try:
        return pd.to_datetime(x).to_pydatetime()
    except Exception:
        return None


def _weeks_until(d: Optional[datetime]) -> Optional[float]:
    if not d:
        return None
    delta = d.date() - datetime.now(SGT).date()
    return delta.days / 7.0


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


def _safe_eval(expr: str, env: Dict[str, Any]) -> bool:
    """
    Very small eval surface: no builtins, no attribute access intended.
    """
    expr = (expr or "").strip()
    if not expr:
        return False
    try:
        return bool(eval(expr, {"__builtins__": {}}, env))
    except Exception:
        return False


# ----------------------------
# Policy evaluation
# ----------------------------

@dataclass
class EvalResult:
    action: str
    flags: str
    reasons: str


def _eval_row(
    row: Dict[str, Any],
    *,
    policy: Dict[str, Any],
    thresholds: Dict[str, Any],
    colmap: Dict[str, str],
) -> EvalResult:
    rules = policy.get("rules") or []
    default_action = ((policy.get("execution") or {}).get("default_action") or "WATCH").upper()

    flags: List[str] = []
    reasons: List[str] = []
    action = default_action

    # computed helpers
    spread_pct = _spread_pct(row.get(colmap.get("Bid", "Bid"), row.get("Bid")), row.get(colmap.get("Ask", "Ask"), row.get("Ask")))
    dte = row.get(colmap.get("DTE", "DTE"), row.get("DTE"))

    # earnings helpers (if present)
    earn_raw = row.get(colmap.get("Earnings", "Earnings"), row.get("Earnings"))
    earn_dt = _parse_date(earn_raw)
    earn_weeks = _weeks_until(earn_dt)
    earnings_missing = earn_dt is None

    env: Dict[str, Any] = {}
    env.update(row)
    env.update(thresholds)
    env["spread_pct"] = spread_pct
    env["dte_val"] = dte
    env["earnings_in_weeks"] = earn_weeks if earn_weeks is not None else 9999.0
    env["earnings_date_missing"] = bool(earnings_missing)

    for r in rules:
        code = str(r.get("code") or "").strip() or "RULE"
        when = _rewrite_expr(str(r.get("when") or ""), colmap)
        status = str(r.get("status") or "").strip().upper() or "REVIEW"
        why = str(r.get("why") or "").strip()

        hit = _safe_eval(when, env)
        if not hit:
            continue

        flags.append(code)
        if why:
            reasons.append(f"{code}: {why}")
        else:
            reasons.append(code)

        # escalation logic:
        # SKIP overrides everything, REVIEW overrides WATCH, EXECUTE only if still WATCH
        if status == "SKIP":
            action = "SKIP"
        elif status == "REVIEW" and action not in ("SKIP",):
            action = "REVIEW"
        elif status == "EXECUTE" and action == "WATCH":
            action = "EXECUTE"

    return EvalResult(
        action=action,
        flags=",".join(flags),
        reasons=" | ".join(reasons),
    )


# ----------------------------
# Commands
# ----------------------------

def cmd_check(args: argparse.Namespace) -> None:
    user_yml = Path(args.user_yml).expanduser().resolve()
    user_cfg = _load_yaml(user_yml)

    cloud_root = _resolve_cloud_path(user_cfg, "")
    policy_rel = (user_cfg.get("policy_source") or {}).get("global_policy") or ""
    if not policy_rel:
        raise SystemExit("lcl.user.yml missing policy_source.global_policy")

    policy_path = (cloud_root / policy_rel).resolve()
    ideas_rel = ((user_cfg.get("ideas_source") or {}).get("latest_excel")) or ""
    if not ideas_rel:
        raise SystemExit("lcl.user.yml missing ideas_source.latest_excel")

    ideas_path = (cloud_root / ideas_rel).resolve()

    print(f"[policy_eval] user_yml: {user_yml}")
    print(f"[policy_eval] module: {args.module}")
    print(f"[policy_eval] cloud_root: {cloud_root}")
    print(f"[policy_eval] policy_yml: {policy_path}")
    print(f"[policy_eval] ideas_excel: {ideas_path}")

    policy = _load_yaml(policy_path)
    module_policy = _get_module_policy(policy, args.module)
    if not module_policy:
        mods = policy.get("modules")
        found = sorted(list(mods.keys())) if isinstance(mods, dict) else []
        raise SystemExit(
            f"Module policy not found in {policy_path} for module={args.module!r}. "
            f"Expected either top-level '{args.module}:' or 'modules.{args.module}'. "
            f"Found modules: {found or '(none)'}"
        )

    df = _read_excel_rows(ideas_path, args.sheet)
    df2, colmap = _normalize_columns(df)

    required = module_policy.get("required_columns") or []
    missing = []
    for col in required:
        if str(col).strip() not in colmap:
            missing.append(str(col))
    if missing:
        raise SystemExit(f"Missing required columns in Excel: {missing}")

    print(f"[policy_eval] rows: {len(df)}")
    print(f"[policy_eval] required_columns ok: {len(required)}")
    print("[policy_eval] OK")


def cmd_run(args: argparse.Namespace) -> None:
    user_yml = Path(args.user_yml).expanduser().resolve()
    user_cfg = _load_yaml(user_yml)

    cloud_root = _resolve_cloud_path(user_cfg, "")
    policy_rel = (user_cfg.get("policy_source") or {}).get("global_policy") or ""
    policy_path = (cloud_root / policy_rel).resolve()

    ideas_rel = ((user_cfg.get("ideas_source") or {}).get("latest_excel")) or ""
    ideas_path = (cloud_root / ideas_rel).resolve()

    policy = _load_yaml(policy_path)
    module_policy = _get_module_policy(policy, args.module)
    if not module_policy:
        mods = policy.get("modules")
        found = sorted(list(mods.keys())) if isinstance(mods, dict) else []
        raise SystemExit(
            f"Module policy not found in {policy_path} for module={args.module!r}. "
            f"Expected either top-level '{args.module}:' or 'modules.{args.module}'. "
            f"Found modules: {found or '(none)'}"
        )

    thresholds = (module_policy.get("thresholds") or {})
    df = _read_excel_rows(ideas_path, args.sheet)
    df2, colmap = _normalize_columns(df)

    # prepare output
    outdir = Path(args.outdir).expanduser().resolve() if args.outdir else (_user_root(user_yml) / "output" / args.module)
    outdir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(SGT).strftime("%Y-%m-%d_%H%M%S")
    out_full = outdir / f"{stamp}_{args.module}_policy_eval.xlsx"
    out_review = outdir / f"{stamp}_{args.module}_policy_review_only.xlsx"

    # eval each row
    actions: List[str] = []
    flags: List[str] = []
    reasons: List[str] = []

    for _, r in df2.iterrows():
        row = r.to_dict()
        res = _eval_row(row, policy=module_policy, thresholds=thresholds, colmap=colmap)
        actions.append(res.action)
        flags.append(res.flags)
        reasons.append(res.reasons)

    df_out = df.copy()
    df_out["Policy Action"] = actions
    df_out["Policy Flags"] = flags
    df_out["Policy Reasons"] = reasons
    df_out["Evaluated At (SGT)"] = _now_sgt_iso()

    with pd.ExcelWriter(out_full, engine="openpyxl") as xw:
        df_out.to_excel(xw, index=False, sheet_name="Evaluated")

    print(f"[policy_eval] wrote: {out_full}")

    if args.only_review:
        df_r = df_out[df_out["Policy Action"].isin(["REVIEW", "SKIP"])].copy()
        with pd.ExcelWriter(out_review, engine="openpyxl") as xw:
            df_r.to_excel(xw, index=False, sheet_name="ReviewOnly")
        print(f"[policy_eval] wrote: {out_review} (rows={len(df_r)})")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TGPS User Policy Evaluator")
    ap.add_argument("--user-yml", default=str(Path("~/tgps-project/tgps-user/config/lcl.user.yml").expanduser()),
                    help="Path to tgps-user lcl.user.yml")
    ap.add_argument("--module", default="sellput", help="Module name (default sellput)")
    ap.add_argument("--sheet", default="", help="Excel sheet name (default first sheet)")
    ap.add_argument("--outdir", default="", help="Output directory (default tgps-user/output/<module>)")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="Check config/policy/ideas are readable and required columns exist")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="Evaluate policy and write output workbook(s)")
    p.add_argument("--only-review", action="store_true", help="Also write a REVIEW/SKIP-only workbook")
    p.set_defaults(func=cmd_run)

    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
