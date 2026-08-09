#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIV-01 readiness validator for OneJournal.

Usage:
    python scripts/liv/validate_readiness.py \
        --checklist docs/live_trading_readiness_checklist.md \
        --evidence-pack docs/live_trading_readiness_evidence_pack.md
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ALLOWED_CHECKLIST_STATUS = {"OK", "WARN", "BLOCKED", "PENDING"}
ALLOWED_EVIDENCE_STATUS = {"OK", "WARN", "BLOCKED", "PENDING"}
PLACEHOLDER_MARKERS = {"placeholder", "TBD", "TODO", "TBA"}
READY_STATUS = "OK"


REQUIRED_LIV_01 = {
    "LIV-01-1 (Legal)": {"evidence_id": "EVID-LIV-01-01"},
    "LIV-01-2 (Security)": {"evidence_id": "EVID-LIV-01-02"},
    "LIV-01-3 (Risk)": {"evidence_id": "EVID-LIV-01-03"},
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate LIV-01 readiness evidence completeness.")
    parser.add_argument(
        "--checklist",
        required=True,
        help="Path to `docs/live_trading_readiness_checklist.md`.",
    )
    parser.add_argument(
        "--evidence-pack",
        required=True,
        help="Path to `docs/live_trading_readiness_evidence_pack.md`.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as hard failures.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable output.",
    )
    return parser.parse_args(argv)


def parse_markdown_table(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| ---"):
            continue
        if line.count("|") < 2:
            continue
        pieces = [piece.strip() for piece in line.strip("|").split("|")]
        rows.append(pieces)
    return rows[1:] if len(rows) > 1 else []


def _is_placeholder(text: str) -> bool:
    normalized = text.lower()
    return any(token in normalized for token in PLACEHOLDER_MARKERS)


def validate_readiness(
    checklist_path: Path,
    evidence_pack_path: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not checklist_path.exists():
        errors.append(f"checklist: file not found: {checklist_path}")
        return errors, warnings
    if not evidence_pack_path.exists():
        errors.append(f"evidence-pack: file not found: {evidence_pack_path}")
        return errors, warnings

    checklist_rows = parse_markdown_table(checklist_path)
    evidence_rows = parse_markdown_table(evidence_pack_path)

    if not checklist_rows:
        errors.append("checklist: evidence table is empty or not parseable.")
        return errors, warnings
    if not evidence_rows:
        errors.append("evidence-pack: evidence table is empty or not parseable.")
        return errors, warnings

    checklist_map = _map_table_rows(checklist_rows, col_key="item")
    evidence_map = _map_table_rows(evidence_rows, col_key="evidence_id")

    for item, payload in REQUIRED_LIV_01.items():
        row = checklist_map.get(item)
        if not row:
            errors.append(f"checklist: missing row for {item}")
            continue
        status = row.get("status", "")
        if status not in ALLOWED_CHECKLIST_STATUS:
            errors.append(f"checklist: {item} has invalid status {status!r}")
            continue
        if status != READY_STATUS:
            warnings.append(f"checklist: {item} is {status}; not ready for LIV-01 completion.")

        evidence_id = payload["evidence_id"]
        evidence_row = evidence_map.get(evidence_id)
        if not evidence_row:
            errors.append(f"evidence-pack: missing evidence row {evidence_id}")
            continue
        artifact = row.get("artifact", "") or evidence_row.get("artifact", "")
        evidence_status = evidence_row.get("status", "")
        if evidence_status not in ALLOWED_EVIDENCE_STATUS:
            errors.append(f"evidence-pack: {evidence_id} has invalid status {evidence_status!r}")
            continue
        if evidence_status != READY_STATUS:
            warnings.append(f"evidence-pack: {evidence_id} is {evidence_status}; not ready for LIV-01 completion.")
        if not artifact:
            errors.append(f"evidence-pack: {evidence_id} is missing linked evidence artifact path.")
            continue
        _check_evidence_template_file(
            Path(artifact),
            expected_id=payload["evidence_id"],
            errors=errors,
            warnings=warnings,
        )

    # check for duplicate/extra LIV-01 evidence ids to avoid conflicting copies
    for evidence_id, row in evidence_map.items():
        queue = row.get("queue", "")
        if evidence_id.startswith("EVID-LIV-01-") and queue != "LIV-01":
            warnings.append(
                f"evidence-pack: {evidence_id} has queue {queue} but evidence id implies LIV-01"
            )

    return errors, warnings


def _map_table_rows(rows: list[list[str]], *, col_key: str) -> dict[str, dict[str, str]]:
    if col_key == "item":
        # checklist: date | item | artifact | status | owner | notes
        key_index = 1
        expected_len = 6
    elif col_key == "evidence_id":
        # evidence pack: evidence_id | queue | artifact | status | owner | timestamp | notes
        key_index = 0
        expected_len = 7
    else:
        raise ValueError(f"invalid table key {col_key!r}")

    mapped: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=1):
        if len(row) < expected_len:
            # skip malformed rows; validation logic handles shape via warning upstream if needed
            continue
        key = row[key_index].strip()
        if key == "":
            continue
        if col_key == "item":
            mapped[key] = {
                "artifact": row[2].strip() if len(row) > 2 else "",
                "status": row[3].strip() if len(row) > 3 else "",
            }
        else:
            mapped[key] = {
                "queue": row[1].strip() if len(row) > 1 else "",
                "status": row[3].strip() if len(row) > 3 else "",
                "artifact": row[2].strip() if len(row) > 2 else "",
            }
    return mapped


def _check_evidence_template_file(
    artifact_path: Path,
    *,
    expected_id: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not artifact_path.exists():
        errors.append(f"evidence-pack: {expected_id} artifact not found: {artifact_path}")
        return

    text = artifact_path.read_text(encoding="utf-8")
    if f"`{expected_id}`" not in text and expected_id not in text:
        warnings.append(
            f"evidence-pack: {expected_id} artifact {artifact_path} is not explicitly linked to this evidence id."
        )

    field_lines = [
        line
        for line in text.splitlines()
        if re.match(r"^- .+: ?$", line) and ":" in line and not line.strip().startswith("- [")
    ]
    placeholder_lines = [line for line in field_lines if _is_placeholder(line)]
    if placeholder_lines:
        warnings.append(
            f"evidence-pack: {artifact_path} contains placeholder markers in required fields ({len(placeholder_lines)} entries)."
        )

    unchecked = [line for line in text.splitlines() if re.match(r"^- \[ \] ", line)]
    if unchecked:
        warnings.append(f"evidence-pack: {artifact_path} has unchecked requirement boxes ({len(unchecked)} entries).")

    empty_field = [line for line in field_lines if re.match(r"^- .+:\\s*$", line)]
    if empty_field:
        warnings.append(
            f"evidence-pack: {artifact_path} has {len(empty_field)} unresolved required fields."
        )


def run_validation(checklist_path: Path, evidence_pack_path: Path, *, strict: bool, as_json: bool) -> int:
    errors, warnings = validate_readiness(checklist_path, evidence_pack_path)
    if as_json:
        print(
            json.dumps(
                {
                    "status": "ok" if not errors else "failed",
                    "errors": errors,
                    "warnings": warnings,
                },
                ensure_ascii=False,
            )
        )
        return 1 if errors or (strict and warnings) else 0

    if errors:
        print("STATUS: failed")
        for issue in errors:
            print(f"- {issue}")
        if strict and warnings:
            print("STRICT MODE: warnings present")
            for issue in warnings:
                print(f"- {issue}")
        return 1

    if warnings and strict:
        print("STATUS: failed (strict)")
        for issue in warnings:
            print(f"- {issue}")
        return 1

    if warnings:
        print("STATUS: WARN")
        for issue in warnings:
            print(f"- {issue}")
        return 0

    print("STATUS: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_validation(
        Path(args.checklist).expanduser(),
        Path(args.evidence_pack).expanduser(),
        strict=args.strict,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
