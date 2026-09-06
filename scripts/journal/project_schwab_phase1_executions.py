#!/usr/bin/env python3
"""Persist the corrected execution-first projection for one exact materialization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat

from onejournal.journal.schwab_execution_projection import (
    persist_schwab_execution_projection,
    privacy_safe_projection_audit,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project one exact Phase 1 materialization into execution-first journal state."
    )
    parser.add_argument("--db", required=True, help="Existing private migration-0019 DuckDB path.")
    parser.add_argument(
        "--materialization-uid",
        required=True,
        help="Exact migration-0018 materialization identity; no latest fallback.",
    )
    return parser.parse_args(argv)


def _private_file(value: str) -> Path:
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise ValueError("database must not be a symlink")
    path = supplied.resolve()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("database must be an existing absolute file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("database must use mode 0600")
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = persist_schwab_execution_projection(
        _private_file(args.db),
        materialization_uid=args.materialization_uid,
    )
    print(json.dumps(privacy_safe_projection_audit(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
