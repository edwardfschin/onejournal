#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/sellput_day.py
Version: 0.6.2 (2026-01-22, SGT)

Single SellPut CLI (one file)
-----------------------------
prep (alias: run)
  Runs the full pipeline and generates an editable queue.
  Prints ONLY the queue_edit path on success.

decide
  Generate a fresh queue_edit from the latest system queue.

plan
  Validate + import actions from queue_edit, then preview exec plan.

submit
  Validate + import actions from queue_edit, then submit orders.

Pipeline steps for prep/run
---------------------------
  doctor check
  init_ledger --check
  sync_ideas run
  ideas_runner plan   -> writes *_sellput_queue_sys.xlsx
  queue_editor patch  -> writes *_sellput_queue_edit.xlsx

Env vars per step:
  TGPS_RUN_ID=<run_id>
  TGPS_STEP=<step_name>

Stability guard (important)
---------------------------
Excel may rewrite .xlsx while you click Save. During that brief window,
openpyxl can crash with:
  zipfile.BadZipFile: File is not a zip file

This wrapper:
  - waits for the queue_edit to look "stable" (zip signature + stable size)
  - retries validate/import if it detects BadZipFile / mid-save symptoms

Change notes (0.6.2)
--------------------
1) Prefer queue_edit that matches the current run_id (if provided) to avoid picking the wrong file.
2) Export TGPS_STEP for actions_capture validate/import for clearer logs and traceability.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


# ----------------------------
# Paths / helpers
# ----------------------------
def _repo_root() -> Path:
    here = Path.cwd().resolve()
    if (here / "tgps-user").exists():
        return here
    for p in [here] + list(here.parents):
        if (p / "tgps-user").exists():
            return p
    raise SystemExit("❌ Could not find repo root (expected 'tgps-user' folder). Run from TradersGPS repo.")


def _user_root(repo: Path) -> Path:
    return repo / "tgps-user"


def _sellput_outdir(user_root: Path) -> Path:
    return user_root / "output" / "sellput"


def _mk_run_id(explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    rid = (os.environ.get("TGPS_RUN_ID") or "").strip()
    if rid:
        return rid
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run_id_to_prefix(run_id: str) -> str:
    """
    Convert TGPS_RUN_ID like YYYYMMDD_HHMMSS -> YYYY-MM-DD_HHMMSS
    to match file prefixes used in outputs.
    """
    rid = (run_id or "").strip()
    if len(rid) >= 15 and "_" in rid:
        d, t = rid.split("_", 1)
        if len(d) == 8 and d.isdigit():
            return f"{d[0:4]}-{d[4:6]}-{d[6:8]}_{t}"
    return rid


def _latest_queue_edit(outdir: Path, *, run_id: str = "") -> Path:
    # Ignore Excel temp/lock files like "~$*.xlsx"
    def ok_file(p: Path) -> bool:
        try:
            return p.is_file() and (not p.name.startswith("~$"))
        except Exception:
            return False

    # 1) If run_id provided, prefer matching prefix
    rid = (run_id or "").strip()
    if rid:
        prefix = _run_id_to_prefix(rid)
        cands = [p for p in outdir.glob(f"*{prefix}*_sellput_queue_edit.xlsx") if ok_file(p)]
        cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)
        for p in cands:
            try:
                if p.stat().st_size >= 2048:
                    return p
            except Exception:
                continue
        if cands:
            return cands[0]

    # 2) Fallback: newest by mtime
    cands = [p for p in outdir.glob("*_sellput_queue_edit.xlsx") if ok_file(p)]
    if not cands:
        raise SystemExit(f"❌ No *_sellput_queue_edit.xlsx found in: {outdir}")

    cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)
    for p in cands:
        try:
            if p.stat().st_size >= 2048:
                return p
        except Exception:
            continue

    return cands[0]


# ----------------------------
# XLSX stability guard (prevents BadZipFile)
# ----------------------------
def _xlsx_has_zip_signature(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            sig = f.read(4)
        return sig in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    except Exception:
        return False


def _wait_for_stable_xlsx(p: Path, *, attempts: int = 12, sleep_s: float = 0.35) -> None:
    """
    Best-effort guard for the "Excel mid-save" window.
    We require:
      - file exists
      - size looks non-trivial
      - zip signature present
      - size stable across two checks
    """
    last_reason: str = "unknown"
    for _ in range(max(1, attempts)):
        try:
            if not p.exists():
                last_reason = "missing"
                time.sleep(sleep_s)
                continue

            s1 = p.stat()
            if s1.st_size < 2048:
                last_reason = f"too small ({s1.st_size} bytes)"
                time.sleep(sleep_s)
                continue

            if not _xlsx_has_zip_signature(p):
                last_reason = "no PK zip signature"
                time.sleep(sleep_s)
                continue

            time.sleep(sleep_s)
            s2 = p.stat()

            if s1.st_size == s2.st_size and _xlsx_has_zip_signature(p):
                return

            last_reason = "size changed (mid-save)"
        except PermissionError:
            last_reason = "permission/lock (Excel may be writing)"
        except Exception as e:
            last_reason = str(e)

        time.sleep(sleep_s)

    raise SystemExit(
        f"❌ Queue workbook looks unstable/unreadable right now:\n"
        f"   {p}\n"
        f"   last_check={last_reason}\n\n"
        f"Fix:\n"
        f" - In Excel: Save, wait 2–3 seconds, try again.\n"
        f" - If it still fails: close the workbook and rerun.\n"
    )


def _looks_like_transient_xlsx_error(text: str) -> bool:
    t = (text or "").lower()
    return (
        ("badzipfile" in t)
        or ("file is not a zip file" in t)
        or ("end of central directory record" in t)
        or ("permission denied" in t)
        or ("resource busy" in t)
        or ("being used by another process" in t)
    )


# ----------------------------
# Subprocess runner
# ----------------------------
def _run(cmd: list[str], *, env_extra: Optional[dict] = None, quiet: bool = False) -> int:
    env = os.environ.copy()
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})

    if quiet:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if p.returncode != 0:
            msg = (p.stderr or "").strip() or (p.stdout or "").strip() or f"exit={p.returncode}"
            print(msg)
        return int(p.returncode)

    return int(subprocess.call(cmd, env=env))


def _run_capture(cmd: list[str], *, env_extra: Optional[dict] = None) -> Tuple[int, str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return int(p.returncode), (p.stdout or ""), (p.stderr or "")


# ----------------------------
# Pipeline
# ----------------------------
def _prep_pipeline(*, run_id: str, skip_doctor: bool, dry: bool, quiet: bool) -> int:
    py = sys.executable

    steps: list[tuple[str, list[str]]] = []

    if not skip_doctor:
        steps.append(("doctor.check", [py, "-m", "scripts.tgps_user.doctor", "check"]))

    steps += [
        ("init_ledger.check", [py, "-m", "scripts.tgps_user.init_ledger", "--check"]),
        ("sync_ideas.run", [py, "-m", "scripts.tgps_user.sync_ideas", "run"]),
        # Do NOT pass --module into ideas_runner (your current ideas_runner rejects it)
        ("ideas_runner.plan", [py, "-m", "scripts.tgps_user.ideas_runner", "plan"]),
        ("queue_editor.patch", [py, "-m", "scripts.tgps_user.queue_editor", "patch"]),
    ]

    if dry:
        for step, cmd in steps:
            print(f"DRY ▶ {step}: {' '.join(cmd)}")
        return 0

    # Run each step. We ALWAYS suppress queue_editor.patch output so we only print the final path once.
    for step, cmd in steps:
        step_quiet = bool(quiet) or (step == "queue_editor.patch")
        rc = _run(cmd, env_extra={"TGPS_RUN_ID": run_id, "TGPS_STEP": step}, quiet=step_quiet)
        if rc != 0:
            if not quiet:
                print(f"❌ {step} FAILED (exit={rc})")
            return rc

    # Success: print ONLY queue_edit path (prefer this run_id)
    repo = _repo_root()
    outdir = _sellput_outdir(_user_root(repo))
    qedit = _latest_queue_edit(outdir, run_id=run_id)
    print(qedit.as_posix())
    return 0


def _validate_and_import(queue_path: Path, *, run_id: str) -> None:
    # Pre-check stability before touching openpyxl downstream
    _wait_for_stable_xlsx(queue_path)

    # Retry validate/import if we detect transient BadZipFile / mid-save conditions
    def run_with_retry(cmd: list[str], label: str, tries: int = 6) -> int:
        last_out = ""
        for i in range(tries):
            rc, out, err = _run_capture(
                cmd,
                env_extra={
                    "TGPS_RUN_ID": run_id,
                    "TGPS_STEP": f"sellput_day.{label}",
                },
            )
            if rc == 0:
                return 0

            combo = (out or "") + "\n" + (err or "")
            last_out = combo.strip()

            if _looks_like_transient_xlsx_error(combo) and i < (tries - 1):
                time.sleep(0.5 + 0.3 * i)
                _wait_for_stable_xlsx(queue_path)
                continue

            if last_out:
                print(last_out)
            return rc

        if last_out:
            print(last_out)
        return 1

    rc = run_with_retry(
        [sys.executable, "-m", "scripts.tgps_user.actions_capture", "validate", "--queue", str(queue_path)],
        "validate",
    )
    if rc != 0:
        raise SystemExit("❌ Queue validation failed. Fix the queue_edit and rerun.")

    rc = run_with_retry(
        [sys.executable, "-m", "scripts.tgps_user.actions_capture", "import", "--queue", str(queue_path)],
        "import",
    )
    if rc != 0:
        raise SystemExit("❌ actions_capture import failed.")


# ----------------------------
# Commands
# ----------------------------
def cmd_prep(args: argparse.Namespace) -> int:
    run_id = _mk_run_id(args.run_id)
    return _prep_pipeline(
        run_id=run_id,
        skip_doctor=bool(args.skip_doctor),
        dry=bool(args.dry),
        quiet=bool(args.quiet),
    )


def cmd_decide(args: argparse.Namespace) -> int:
    env_extra = {"TGPS_STEP": "sellput_day.decide"}
    if args.run_id.strip():
        env_extra["TGPS_RUN_ID"] = _mk_run_id(args.run_id)
    return _run([sys.executable, "-m", "scripts.tgps_user.queue_editor", "patch"], env_extra=env_extra)


def cmd_plan(args: argparse.Namespace) -> int:
    repo = _repo_root()
    outdir = _sellput_outdir(_user_root(repo))

    run_id = _mk_run_id(args.run_id)

    queue_path = Path(args.queue).expanduser().resolve() if args.queue else _latest_queue_edit(outdir, run_id=run_id)
    if not queue_path.exists():
        raise SystemExit(f"❌ Queue not found: {queue_path}")

    _validate_and_import(queue_path, run_id=run_id)

    cmd = [sys.executable, "-m", "scripts.tgps_user.exec_plan", "preview", "--module", args.module]

    if args.account:
        cmd += ["--account", args.account]
    if args.tickers:
        cmd += ["--tickers", args.tickers]
    if args.journal_db:
        cmd += ["--journal-db", args.journal_db]
    if args.limit and int(args.limit) > 0:
        cmd += ["--limit", str(int(args.limit))]
    if args.force:
        cmd += ["--force"]

    return _run(cmd, env_extra={"TGPS_RUN_ID": run_id, "TGPS_STEP": "sellput_day.plan"})


def cmd_submit(args: argparse.Namespace) -> int:
    repo = _repo_root()
    outdir = _sellput_outdir(_user_root(repo))

    run_id = _mk_run_id(args.run_id)

    queue_path = Path(args.queue).expanduser().resolve() if args.queue else _latest_queue_edit(outdir, run_id=run_id)
    if not queue_path.exists():
        raise SystemExit(f"❌ Queue not found: {queue_path}")

    _validate_and_import(queue_path, run_id=run_id)

    cmd = [sys.executable, "-m", "scripts.tgps_user.exec_plan", "submit", "--module", args.module]

    if args.account:
        cmd += ["--account", args.account]
    if args.tickers:
        cmd += ["--tickers", args.tickers]
    if args.journal_db:
        cmd += ["--journal-db", args.journal_db]
    if args.limit and int(args.limit) > 0:
        cmd += ["--limit", str(int(args.limit))]
    if args.force:
        cmd += ["--force"]

    return _run(cmd, env_extra={"TGPS_RUN_ID": run_id, "TGPS_STEP": "sellput_day.submit"})


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="SellPut Day CLI (prep/run/decide/plan/submit)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="Run pipeline + generate editable queue (prints queue_edit path)")
    p.add_argument("--skip-doctor", action="store_true", help="Skip doctor check (not recommended)")
    p.add_argument("--dry", action="store_true", help="Print commands only; do not execute")
    p.add_argument("--quiet", action="store_true", help="Capture step output (only prints errors + final path)")
    p.add_argument("--run-id", default="", help="Optional explicit run id (default: env TGPS_RUN_ID or now)")
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("run", help="Alias for prep (backward compatible)")
    p.add_argument("--skip-doctor", action="store_true")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--run-id", default="")
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("decide", help="Generate a fresh queue_edit from latest system queue")
    p.add_argument("--run-id", default="", help="Optional: set TGPS_RUN_ID (otherwise use latest sys queue)")
    p.set_defaults(func=cmd_decide)

    def add_exec_args(px: argparse.ArgumentParser) -> None:
        px.add_argument("--queue", default="", help="Optional path to *_sellput_queue_edit.xlsx (default: latest)")
        px.add_argument("--module", default="sellput", help="Module name (default: sellput)")
        px.add_argument("--account", default="", help="Schwab account number or account hash (optional)")
        px.add_argument("--tickers", default="", help="Optional: comma-separated ticker filter (passes to exec_plan)")
        px.add_argument("--journal-db", default="", help="Optional: journal DuckDB path (passes to exec_plan)")
        px.add_argument("--limit", type=int, default=0, help="Limit OK orders (0 = all)")
        px.add_argument("--force", action="store_true", help="Bypass safety de-dupe (dangerous)")
        px.add_argument("--run-id", default="", help="Optional explicit run id (default: env TGPS_RUN_ID or now)")

    p = sub.add_parser("plan", help="Validate/import actions + preview execution plan")
    add_exec_args(p)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("submit", help="Validate/import actions + submit orders")
    add_exec_args(p)
    p.set_defaults(func=cmd_submit)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
