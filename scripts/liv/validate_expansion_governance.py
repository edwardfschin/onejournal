#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIV-05 governance validator for OneJournal.

Usage:
    python scripts/liv/validate_expansion_governance.py \
        --decision-log docs/live_trading_readiness_decision_log.md \
        --evidence-pack docs/live_trading_readiness_evidence_pack.md
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_DECISION_STATUS = {"COMPLETED", "BLOCKED", "CHANGES_REQUIRED", "DEFERRED"}
ALLOWED_EVIDENCE_STATUS = {"OK", "PENDING", "BLOCKED", "WARN", "IN_REVIEW"}
ALLOWED_QUEUE = {"LIV-01", "LIV-02", "LIV-03", "LIV-04", "LIV-05"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate LIV-05 governance artifacts for safe expansion review.")
    parser.add_argument(
        "--decision-log",
        required=True,
        help="Path to `docs/live_trading_readiness_decision_log.md`.",
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
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
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
    if not rows:
        return []
    # discard header and divider rows (first row usually headers)
    return rows[1:] if len(rows) > 1 else []


def _validate_decision_rows(rows: list[list[str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("decision-log: evidence table is missing rows")
        return errors, warnings
    for i, row in enumerate(rows, start=1):
        if len(row) < 8:
            errors.append(f"decision-log: row {i} has insufficient columns: {len(row)}")
            continue
        date_str, queue, status, _artifacts, approver, role, rationale, next_action = [cell.strip() for cell in row[:8]]

        if queue not in ALLOWED_QUEUE:
            errors.append(f"decision-log row {i}: invalid queue value {queue!r}")
        if status not in ALLOWED_DECISION_STATUS:
            errors.append(f"decision-log row {i}: invalid status {status!r}")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            try:
                datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                errors.append(f"decision-log row {i}: date must be ISO-like (YYYY-MM-DD) got {date_str!r}")

        if status == "DEFERRED":
            warnings.append(f"decision-log row {i}: LIV stage deferred ({queue})")
        if status in {"BLOCKED", "CHANGES_REQUIRED"} and not rationale:
            errors.append(f"decision-log row {i}: status {status} requires rationale")
        if status == "COMPLETED":
            if not approver or not role:
                errors.append(f"decision-log row {i}: COMPLETED requires approver and approver role")
            if not next_action:
                warnings.append(f"decision-log row {i}: COMPLETED but next action missing")

        if queue == "LIV-05" and status == "DEFERRED":
            warnings.append("LIV-05 remains deferred; no expansion can be approved yet.")

    return errors, warnings


def _validate_evidence_rows(rows: list[list[str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("evidence-pack: evidence table is missing rows")
        return errors, warnings
    for i, row in enumerate(rows, start=1):
        if len(row) < 6:
            errors.append(f"evidence-pack: row {i} has insufficient columns: {len(row)}")
            continue
        evidence_id, queue, _artifact, status = [cell.strip() for cell in row[:4]]
        if status not in ALLOWED_EVIDENCE_STATUS:
            errors.append(f"evidence-pack row {i} ({evidence_id}): invalid status {status!r}")
        if not evidence_id.startswith("EVID-LIV-"):
            warnings.append(f"evidence-pack row {i}: evidence id {evidence_id!r} is not LIV-scoped")
        if status != "OK":
            warnings.append(f"evidence-pack row {i} ({evidence_id}): status {status}")
        if status in {"BLOCKED", "PENDING"}:
            if queue in {"LIV-02", "LIV-03", "LIV-04", "LIV-05"}:
                warnings.append(f"evidence-pack row {i} ({evidence_id}): readiness not complete for {queue}")
    return errors, warnings


def validate_governance(decision_log: Path, evidence_pack: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not decision_log.exists():
        errors.append(f"decision-log: missing file {decision_log}")
        return errors, warnings
    if not evidence_pack.exists():
        errors.append(f"evidence-pack: missing file {evidence_pack}")
        return errors, warnings

    try:
        decision_rows = parse_markdown_table(decision_log)
        evidence_rows = parse_markdown_table(evidence_pack)
        d_errors, d_warnings = _validate_decision_rows(decision_rows)
        e_errors, e_warnings = _validate_evidence_rows(evidence_rows)
        errors.extend(d_errors)
        errors.extend(e_errors)
        warnings.extend(d_warnings)
        warnings.extend(e_warnings)
    except Exception as exc:  # pragma: no cover
        errors.append(str(exc))

    return errors, warnings


def run_validation(decision_log: Path, evidence_pack: Path, *, strict: bool, as_json: bool) -> int:
    errors, warnings = validate_governance(decision_log, evidence_pack)
    if as_json:
        print(
            _format_json({
                "status": "ok" if not errors else "failed",
                "errors": errors,
                "warnings": warnings,
            })
        )
        if errors or (strict and warnings):
            return 1
        return 0

    if errors:
        print("STATUS: failed")
        for issue in errors:
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


def _format_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_validation(Path(args.decision_log).expanduser(), Path(args.evidence_pack).expanduser(), strict=args.strict, as_json=args.json)


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
