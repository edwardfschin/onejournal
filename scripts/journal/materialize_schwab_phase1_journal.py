#!/usr/bin/env python3
"""Materialize one accepted Schwab Phase 1 assembly into a private journal.

The command has no provider, credential, database-creation, migration, raw-file
write, or order capability. Both input files must already exist with mode 0600.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
from typing import Sequence

import duckdb


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.journal.schwab_evidence_assembly import (  # noqa: E402
    load_schwab_phase1_evidence_assembly_bytes,
)
from onejournal.journal.schwab_evidence_import_repository import (  # noqa: E402
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (  # noqa: E402
    persist_schwab_journal_materialization,
    privacy_safe_materialization_audit,
)


def _private_file(path: Path, field_name: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{field_name} must be a non-symlink regular file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError(f"{field_name} must have mode 0600")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembly",
        required=True,
        type=Path,
        help="absolute path to an immutable mode-0600 Phase 1 assembly artifact",
    )
    parser.add_argument(
        "--db",
        required=True,
        type=Path,
        help="absolute path to a pre-existing mode-0600 migration-0018 journal",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assembly_path = _private_file(args.assembly, "assembly")
        db_path = _private_file(args.db, "db")
        assembly = load_schwab_phase1_evidence_assembly_bytes(
            assembly_path.read_bytes()
        )
        evidence_result = persist_schwab_phase1_evidence_assembly(db_path, assembly)
        result = persist_schwab_journal_materialization(db_path, assembly)
        audit = privacy_safe_materialization_audit(result)
        audit["evidence_operation"] = (
            "persisted" if evidence_result.created else "replayed"
        )
        print(json.dumps(audit, sort_keys=True, separators=(",", ":")))
        return 0
    except (duckdb.Error, OSError, RuntimeError, ValueError) as exc:
        print(f"Schwab Phase 1 journal materialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
