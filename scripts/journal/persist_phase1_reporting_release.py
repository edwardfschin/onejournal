#!/usr/bin/env python3
"""Validate or explicitly persist one prepared WEB-W08 report release.

Dry-run is the default. The command rebuilds the exact release from the live
journal and the value-free prepared package. ``--persist`` additionally
requires a distinct byte-identical private backup. It cannot migrate the
database, call a provider, place an order, or restart the API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.journal.phase1_reporting_persistence_operator import (  # noqa: E402
    AUTHORIZATION_FILENAME,
    execute_reporting_release_persistence,
    prepare_reporting_release_from_package,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or explicitly persist one exact prepared WEB-W08 "
            "report release; dry-run is the default"
        )
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--broker-current-authorization", required=True, type=Path
    )
    parser.add_argument("--prepared-package", required=True, type=Path)
    parser.add_argument("--expected-database-sha256", required=True)
    parser.add_argument("--expected-report-fingerprint", required=True)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist the exact release after every validation passes",
    )
    parser.add_argument(
        "--verified-backup",
        type=Path,
        help="Distinct byte-identical 0600 backup required with --persist",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.persist and args.verified_backup is None:
        parser.error("--verified-backup is required with --persist")
    if not args.persist and args.verified_backup is not None:
        parser.error("--verified-backup is accepted only with --persist")

    try:
        release = prepare_reporting_release_from_package(
            db_path=args.db,
            broker_current_authorization_path=(
                args.broker_current_authorization
            ),
            package_dir=args.prepared_package,
        )
        execution = execute_reporting_release_persistence(
            args.db,
            release=release,
            authorization_path=(
                args.prepared_package / AUTHORIZATION_FILENAME
            ),
            expected_database_sha256=args.expected_database_sha256,
            expected_report_release_fingerprint=(
                args.expected_report_fingerprint
            ),
            persist=args.persist,
            verified_backup_path=args.verified_backup,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    print(
        json.dumps(
            execution.privacy_safe_audit(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
