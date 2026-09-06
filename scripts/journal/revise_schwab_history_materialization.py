#!/usr/bin/env python3
"""Append one validated Schwab history reconstruction and make it current.

This command cannot call Schwab, discover credentials, create a database, apply
migrations, delete rows, or calculate P&L.  The assembly and database must be
explicit absolute mode-0600 files.
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
from onejournal.journal.schwab_evidence_v2_repository import (  # noqa: E402
    persist_schwab_phase1_evidence_assembly_v2,
)
from onejournal.journal.schwab_history_revision import (  # noqa: E402
    persist_schwab_history_revision,
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
    parser.add_argument("--assembly", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--predecessor-materialization-uid",
        required=True,
        help="exact currently active materialization identity",
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
        evidence = persist_schwab_phase1_evidence_assembly_v2(db_path, assembly)
        result = persist_schwab_history_revision(
            db_path,
            assembly,
            predecessor_materialization_uid=args.predecessor_materialization_uid,
        )
        print(
            json.dumps(
                {
                    "contract_version": "onejournal.history-materialization-revision.v1",
                    "operation": "created" if result.created else "replayed",
                    "revision_uid": result.revision_uid,
                    "activation_uid": result.activation_uid,
                    "activation_sequence": result.activation_sequence,
                    "predecessor_revision_uid": result.predecessor_revision_uid,
                    "evidence_operation": (
                        "persisted" if evidence.created else "replayed"
                    ),
                    "fill_count": result.fill_count,
                    "new_fill_count": result.new_fill_count,
                    "reused_fill_count": result.reused_fill_count,
                    "episode_count": result.episode_count,
                    "final_status": result.final_status,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (duckdb.Error, OSError, RuntimeError, ValueError) as exc:
        print(f"Schwab history revision failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
