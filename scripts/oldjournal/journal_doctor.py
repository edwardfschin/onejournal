#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/journal_doctor.py
Version: 1.0.0 (2025-11-20, SGT)

Purpose
-------
One-stop "doctor" for the Schwab Trade Journal DuckDB.

It orchestrates:
  1) db_inspect          – quick schema + row-count overview
  2) audit_trades        – detailed checks on journal.trades
  3) introspect_journal  – optional deep structural dump

By default it runs (1) and (2). You can opt-in to (3).

CLI examples
------------
    # Standard health check (inspect + audit)
    python -m scripts.journal.doctor

    # Restrict audit window and show duplicates
    python -m scripts.journal.doctor --from 2025-01-01 --to 2025-11-19 --show-dups

    # Include deep introspection
    python -m scripts.journal.doctor --introspect
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List

DEFAULT_DB = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run combined health checks on the Schwab Trade Journal DuckDB."
    )
    p.add_argument(
        "--db",
        default=DEFAULT_DB,
        help="Path to DuckDB file (default: %(default)s)",
    )
    p.add_argument(
        "--schema",
        default="journal",
        help="Schema to inspect (default: journal)",
    )

    # Window forwarded to audit_trades
    p.add_argument(
        "--from",
        dest="date_from",
        default="",
        help="Start date (YYYY-MM-DD) for audit_trades window.",
    )
    p.add_argument(
        "--to",
        dest="date_to",
        default="",
        help="End date (YYYY-MM-DD) for audit_trades window.",
    )

    p.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Sample N rows in audit_trades.",
    )
    p.add_argument(
        "--show-dups",
        action="store_true",
        help="Show duplicate groups in audit_trades.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any sub-check fails.",
    )

    # Which sub-steps to run
    p.add_argument(
        "--no-inspect",
        action="store_true",
        help="Skip db_inspect.",
    )
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip audit_trades.",
    )
    p.add_argument(
        "--introspect",
        action="store_true",
        help="Also run introspect_journal (deep dump).",
    )

    return p.parse_args()


def run_cmd(label: str, cmd: List[str]) -> int:
    print()
    print(f"=== [{label}] RUNNING: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd)
        print(f"=== [{label}] EXIT CODE: {proc.returncode}")
        return proc.returncode
    except Exception as e:
        print(f"=== [{label}] ERROR: {e}")
        return 1


def main() -> None:
    args = parse_args()
    db_path = os.path.expanduser(args.db)

    if not os.path.exists(db_path):
        print(f"[doctor] ❌ DB not found: {db_path}")
        sys.exit(1)

    overall_rc = 0

    # 1) db_inspect
    if not args.no_inspect:
        cmd = [
            sys.executable,
            "-m",
            "scripts.journal.db_inspect",
            "--db",
            db_path,
            "--schema",
            args.schema,
        ]
        rc = run_cmd("db_inspect", cmd)
        overall_rc = max(overall_rc, rc)

    # 2) audit_trades
    if not args.no_audit:
        cmd = [
            sys.executable,
            "-m",
            "scripts.journal.audit_trades",
            "--db",
            db_path,
        ]
        if args.date_from:
            cmd.extend(["--from", args.date_from])
        if args.date_to:
            cmd.extend(["--to", args.date_to])
        if args.sample:
            cmd.extend(["--sample", str(args.sample)])
        if args.show_dups:
            cmd.append("--show-dups")
        if args.strict:
            cmd.append("--strict")

        rc = run_cmd("audit_trades", cmd)
        overall_rc = max(overall_rc, rc)

    # 3) introspect_journal (opt-in, since it can be noisy)
    if args.introspect:
        cmd = [
            sys.executable,
            "-m",
            "scripts.journal.introspect_journal",
            "--db",
            db_path,
        ]
        rc = run_cmd("introspect_journal", cmd)
        overall_rc = max(overall_rc, rc)

    if args.strict and overall_rc != 0:
        sys.exit(overall_rc)
    # In non-strict mode, always exit 0 so you can just read the output.
    sys.exit(0)


if __name__ == "__main__":
    main()
