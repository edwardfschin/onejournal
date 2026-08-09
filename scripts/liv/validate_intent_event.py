#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIV-03 order-intent contract validator.

Usage:
    python scripts/liv/validate_intent_event.py --payload intent.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_SIDE = {"BUY", "SELL"}
ALLOWED_ASSET_CLASS = {"OPTION", "STOCK", "CASH"}
ALLOWED_ORDER_TYPE = {"LIMIT", "MARKET"}
ALLOWED_RISK_STATUS = {"PASS", "WARN", "FAIL", "BLOCKED"}
ALLOWED_APPROVAL_STATUS = {"PENDING", "APPROVED", "DENIED", "EXPIRED"}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal order-intent payload.")
    parser.add_argument("--payload", required=True, help="JSON/YAML intent payload path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as hard failures.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result.")
    return parser.parse_args(argv)


def parse_datetime(value: str | None, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: required ISO-8601 timestamp.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}: invalid ISO-8601 timestamp {value!r}") from exc
    return value.strip()


def require_str(obj: dict[str, Any], field: str) -> str:
    if not isinstance(obj.get(field), str) or not str(obj[field]).strip():
        raise ValueError(f"{field}: required non-empty string.")
    return str(obj[field]).strip()


def require_positive_number(obj: dict[str, Any], field: str) -> float:
    value = obj.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected number.")
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field}: must be > 0.")
    return number


def _validate_enum(obj: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = require_str(obj, field).upper()
    if value not in allowed:
        raise ValueError(f"{field}: {value!r} invalid; allowed={sorted(allowed)}")
    obj[field] = value
    return value


def validate_intent_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        intent_id = require_str(payload, "intent_id")
        if not UUID_RE.match(intent_id):
            raise ValueError("intent_id: must be UUID format.")

        require_str(payload, "source_signal_id")
        require_str(payload, "account_id")
        broker = require_str(payload, "broker")
        if not broker:
            raise ValueError("broker: required")

        symbol = require_str(payload, "symbol")
        if not symbol:
            raise ValueError("symbol: required")

        _validate_enum(payload, "side", ALLOWED_SIDE)
        _validate_enum(payload, "asset_class", ALLOWED_ASSET_CLASS)
        _validate_enum(payload, "order_type", ALLOWED_ORDER_TYPE)
        require_positive_number(payload, "quantity")

        if payload.get("order_type") in {"LIMIT", "STOP"} and "limit_price" not in payload:
            errors.append("limit_price required for limit/stop orders.")
        elif "limit_price" in payload:
            limit_price = float(payload["limit_price"])
            if limit_price < 0:
                errors.append("limit_price: must be >= 0.")

        require_str(payload, "strategy_id")
        parse_datetime(payload.get("created_at") if isinstance(payload.get("created_at"), str) else None, "created_at")
        risk_status = _validate_enum(payload, "risk_status", ALLOWED_RISK_STATUS)
        approval_status = _validate_enum(payload, "approval_status", ALLOWED_APPROVAL_STATUS)
        require_str(payload, "pilot_version")
        require_str(payload, "idempotency_key")
        require_str(payload, "status")

        if approval_status == "APPROVED":
            require_str(payload, "approved_by")
            parse_datetime(payload.get("approved_at") if isinstance(payload.get("approved_at"), str) else None, "approved_at")
            if risk_status != "PASS":
                warnings.append("approval_status=APPROVED while risk_status is not PASS")
        elif approval_status == "PENDING":
            if payload.get("approved_by") is not None and str(payload["approved_by"]).strip():
                warnings.append("approved_by present while approval_status is PENDING")
            if payload.get("approved_at") is not None:
                warnings.append("approved_at present while approval_status is PENDING")

        if payload.get("risk_status") == "BLOCKED":
            warnings.append("risk_status is BLOCKED; runtime must fail closed.")

        if payload.get("status") in {"REJECTED", "FAILED", "ERROR"}:
            warnings.append("intent status indicates already terminal path; check downstream deduplication.")

    except ValueError as exc:
        errors.append(str(exc))

    return errors, warnings


def validate_file(path: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload must be a mapping/object")
    errors, warnings = validate_intent_payload(payload)
    return payload, errors, warnings


def run_validation(path: Path, strict: bool, as_json: bool) -> int:
    try:
        _, errors, warnings = validate_file(path)
    except Exception as exc:  # pragma: no cover
        if as_json:
            print(json.dumps({"status": "failed", "errors": [str(exc)], "warnings": []}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}")
        return 1

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

    print(f"Validating: {path}")
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_validation(Path(args.payload).expanduser(), strict=args.strict, as_json=args.json)


if __name__ == "__main__":
    import sys

    sys.exit(main())
