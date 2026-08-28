#!/usr/bin/env python3
"""Validate or persist one restart-safe private quote capture.

This operator has no provider, credential, migration, order, scheduling, or raw
evidence write capability. Database persistence requires the explicit --persist
flag and an existing database with migrations 0011 and 0012 already applied.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.market_data import QuoteEvidenceSource, load_market_data_policy  # noqa: E402
from onejournal.market_data.runtime import (  # noqa: E402
    persist_durable_quote_capture,
    validate_durable_quote_capture,
)
from onejournal.provider_connectors import LocalPrivateRawCaptureStore  # noqa: E402


MARKETDATA_CONFIG_PATH = PROJECT_DIR / "config" / "marketdata.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or persist one immutable private quote capture"
    )
    parser.add_argument("--private-vault-root", required=True, type=Path)
    parser.add_argument("--source-locator", required=True)
    parser.add_argument("--raw-sha256", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--connection-uid", required=True)
    parser.add_argument("--quote-run-uid", required=True)
    parser.add_argument("--asof", required=True, type=date.fromisoformat)
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Atomically write to an already migrated journal database and read it back",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.persist and args.db is None:
        parser.error("--db is required with --persist")
    if not args.persist and args.db is not None:
        parser.error("--db is accepted only with --persist")
    policy = load_market_data_policy(MARKETDATA_CONFIG_PATH).freshness
    store = LocalPrivateRawCaptureStore(private_root=args.private_vault_root)
    source = QuoteEvidenceSource(
        storage_kind="external_private_vault",
        locator=args.source_locator,
        raw_sha256=args.raw_sha256,
    )
    common = {
        "private_capture_store": store,
        "source": source,
        "policy": policy,
        "expected_provider": args.provider,
        "expected_connection_uid": args.connection_uid,
        "expected_quote_run_uid": args.quote_run_uid,
        "expected_asof": args.asof,
    }
    if args.persist:
        assert args.db is not None
        audit = persist_durable_quote_capture(db_path=args.db, **common)
    else:
        _, audit = validate_durable_quote_capture(**common)
    print(audit.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
