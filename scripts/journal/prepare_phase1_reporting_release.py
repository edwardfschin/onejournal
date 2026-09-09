#!/usr/bin/env python3
"""Prepare and rehearse one exact WEB-W08 reporting release."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from onejournal.journal.phase1_reporting_persistence_operator import (
    prepare_owner_accepted_reporting_release,
    rehearse_reporting_release,
    write_private_release_package,
)


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare an exact owner-accepted WEB-W08 release, persist it only to "
            "a new disposable database copy, and write a value-free private package."
        )
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--broker-current-authorization", required=True)
    parser.add_argument("--account-alias", required=True)
    parser.add_argument("--expected-realized-fingerprint", required=True)
    parser.add_argument("--realized-owner-acceptance-uid", required=True)
    parser.add_argument("--realized-owner-accepted-at", required=True, type=_instant)
    parser.add_argument("--report-release-uid", required=True)
    parser.add_argument("--generated-at", required=True, type=_instant)
    parser.add_argument("--report-owner-acceptance-uid", required=True)
    parser.add_argument("--report-owner-accepted-at", required=True, type=_instant)
    parser.add_argument("--rehearsal-db", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.db)
    release = prepare_owner_accepted_reporting_release(
        db_path=source,
        broker_current_authorization_path=Path(args.broker_current_authorization),
        account_alias=args.account_alias,
        expected_realized_result_fingerprint=args.expected_realized_fingerprint,
        realized_owner_acceptance_uid=args.realized_owner_acceptance_uid,
        realized_owner_accepted_at_utc=args.realized_owner_accepted_at,
        report_release_uid=args.report_release_uid,
        generated_at_utc=args.generated_at,
        report_owner_acceptance_uid=args.report_owner_acceptance_uid,
        report_owner_accepted_at_utc=args.report_owner_accepted_at,
    )
    rehearsal = rehearse_reporting_release(
        source_db_path=source,
        rehearsal_db_path=Path(args.rehearsal_db),
        release=release,
    )
    write_private_release_package(
        output_dir=Path(args.output_dir), release=release, rehearsal=rehearsal
    )
    print("===== OneJournal WEB-W08 release preparation =====")
    print("MODE                     : disposable-copy rehearsal")
    print(f"REPORT_RELEASE_UID       : {release.report_release_uid}")
    print(f"REPORT_FINGERPRINT       : {release.report_release_fingerprint}")
    print(f"ACCOUNT_ALIAS            : {release.accounts[0].account_alias}")
    print(f"AVAILABLE_ALLOCATIONS    : {len(release.items)}")
    print(f"WITHHELD_SCOPES          : {len(release.omissions)}")
    print(f"QUALITY                  : {'incomplete' if release.omissions else 'valid'}")
    print("LIVE_DATABASE_WRITE      : no")
    print("API_RESTART              : no")
    print("PROVIDER_OR_ORDER_ACCESS : no")
    print("IDENTICAL_REPLAY         : passed")
    print("READ_BACK                : passed")
    print("SOURCE_UNCHANGED         : passed")
    print("STATUS                   : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
