#!/usr/bin/env python3
"""Create or revise a private OneJournal entry in DuckDB.

The command writes only the durable journal domain, reads content from a file
or standard input, and never prints private body text. It does not call broker
APIs or alter broker, fill, lifecycle, position, P&L, or execution state.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import duckdb

from onejournal.journal.domain import (
    ENTRY_STATUSES,
    ENTRY_TYPES,
    EntryRevision,
    JournalPolicyError,
    create_entry,
    revise_entry,
    table_exists,
)


DEFAULT_DB = Path("data/journal/onejournal.duckdb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or revise one private journal entry.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB journal path.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    create = subparsers.add_parser("create", help="Create entry identity and revision 1.")
    create.add_argument("--entry-type", required=True, choices=sorted(ENTRY_TYPES))
    _add_content_arguments(create)

    revise = subparsers.add_parser("revise", help="Append a revision to an existing entry.")
    revise.add_argument("--entry-uid", required=True)
    revise.add_argument("--entry-type", choices=sorted(ENTRY_TYPES))
    revise.add_argument("--entry-status", choices=sorted(ENTRY_STATUSES))
    revise.add_argument("--change-reason", required=True)
    _add_content_arguments(revise)
    return parser.parse_args()


def _add_content_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--body-file",
        required=True,
        help="UTF-8 body file, or '-' to read standard input; content is never logged.",
    )
    parser.add_argument("--episode-uid")
    parser.add_argument("--strategy-uid")
    parser.add_argument("--title")
    parser.add_argument("--occurred-at", help="ISO-8601 timestamp; timezone recommended.")


def read_private_body(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def parse_optional_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("--occurred-at must be a valid ISO-8601 timestamp") from exc


def write_entry(db_path: Path, args: argparse.Namespace, body: str) -> EntryRevision:
    if not db_path.exists():
        raise FileNotFoundError(f"journal database not found: {db_path}")
    con = duckdb.connect(str(db_path))
    try:
        if not table_exists(con, "journal_entry_revisions"):
            raise JournalPolicyError(
                "durable journal schema is unavailable; migration 0005 must be approved and applied first"
            )
        common = {
            "body": body,
            "episode_uid": args.episode_uid,
            "strategy_uid": args.strategy_uid,
            "title": args.title,
            "occurred_at": parse_optional_timestamp(args.occurred_at),
        }
        if args.action == "create":
            return create_entry(
                con,
                entry_type=args.entry_type,
                created_source="operator",
                **common,
            )
        return revise_entry(
            con,
            entry_uid=args.entry_uid,
            entry_type=args.entry_type,
            entry_status=args.entry_status,
            change_reason=args.change_reason,
            **common,
        )
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    revision = write_entry(Path(args.db), args, read_private_body(args.body_file))
    print("===== OneJournal private journal entry write =====")
    print(f"DB          : {args.db}")
    print(f"ACTION      : {args.action}")
    print(f"ENTRY_UID   : {revision.entry_uid}")
    print(f"REVISION_NO : {revision.revision_no}")
    print(f"ENTRY_TYPE  : {revision.entry_type}")
    print("CONTENT     : private; not printed")
    print("AUTO TRADE  : disabled")
    print("STATUS      : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
