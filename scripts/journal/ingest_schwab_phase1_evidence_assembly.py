#!/usr/bin/env python3
"""Validate or persist one pre-built Phase 1 Schwab evidence assembly.

The operator has no provider, credential, migration, raw-evidence write, or
order capability. Validation is the default; persistence requires --persist
and a pre-existing database with migration 0016 already applied.
"""

from __future__ import annotations

import argparse
import duckdb
import json
from pathlib import Path
import stat
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.journal.schwab_evidence_assembly import (  # noqa: E402
    load_schwab_phase1_evidence_assembly_bytes,
    privacy_safe_schwab_evidence_audit,
)
from onejournal.journal.schwab_evidence_import_repository import (  # noqa: E402
    load_schwab_phase1_evidence_assembly,
    persist_schwab_phase1_evidence_assembly,
)


class SchwabEvidenceIngestionError(RuntimeError):
    """Raised when the operator's private-input or read-back gate fails."""


def _private_file(path: Path, field_name: str) -> Path:
    if not path.is_absolute():
        raise SchwabEvidenceIngestionError(f"{field_name} must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise SchwabEvidenceIngestionError(
            f"{field_name} must be a non-symlink regular file"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise SchwabEvidenceIngestionError(f"{field_name} must have mode 0600")
    return path


def _database_file(path: Path) -> Path:
    checked = _private_file(path, "db")
    return checked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembly",
        required=True,
        type=Path,
        help="absolute path to a pre-existing 0600 assembly artifact",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="atomically persist after validation",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="absolute path to a pre-existing 0600 DuckDB with migration 0016",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.persist and args.db is None:
        parser.error("--db is required with --persist")
    if not args.persist and args.db is not None:
        parser.error("--db is accepted only with --persist")

    try:
        artifact_path = _private_file(args.assembly, "assembly")
        assembly = load_schwab_phase1_evidence_assembly_bytes(
            artifact_path.read_bytes()
        )
        audit = dict(privacy_safe_schwab_evidence_audit(assembly))
        audit["operation"] = "validated"
        if args.persist:
            db_path = _database_file(args.db)
            result = persist_schwab_phase1_evidence_assembly(db_path, assembly)
            loaded = load_schwab_phase1_evidence_assembly(
                db_path, assembly_uid=assembly.assembly_uid
            )
            if loaded.result_fingerprint != assembly.result_fingerprint:
                raise SchwabEvidenceIngestionError(
                    "persisted assembly failed exact read-back"
                )
            audit.update(
                {
                    "operation": "persisted" if result.created else "replayed",
                    "persisted_family_count": result.family_count,
                    "persisted_record_count": result.normalized_record_count,
                    "readback_verified": True,
                }
            )
        print(json.dumps(audit, sort_keys=True, separators=(",", ":")))
        return 0
    except (duckdb.Error, OSError, RuntimeError, ValueError) as exc:
        print(f"Schwab Phase 1 evidence ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
