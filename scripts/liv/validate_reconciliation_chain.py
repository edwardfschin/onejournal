#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIV-04 reconciliation-chain validator for OneJournal.

Usage:
    python scripts/liv/validate_reconciliation_chain.py \
        --manifest path/to/reconciliation_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_INTENT_APPROVAL_STATUS = {"PENDING", "APPROVED", "DENIED", "EXPIRED"}
ALLOWED_RISK_STATUS = {"PASS", "WARN", "FAIL", "BLOCKED"}
ALLOWED_INTENT_STATUS = {
    "NEW",
    "REVIEWED",
    "APPROVED",
    "DISPATCHED",
    "FILLED",
    "REJECTED",
    "FAILED",
    "ERROR",
}
ALLOWED_ORDER_STATUS = {"REVIEWED", "SUBMITTED", "PARTIAL", "FILLED", "REJECTED", "FAILED", "ERROR"}

REQUIRED_TOP_LEVEL_KEYS = ("intents_csv", "broker_orders_csv", "fills_csv", "asof")

REQUIRED_INTENT_COLUMNS = ("intent_id", "account_id", "broker", "status", "risk_status", "approval_status")
REQUIRED_ORDER_COLUMNS = ("broker_order_id", "intent_id", "status", "quantity", "created_at")
REQUIRED_FILL_COLUMNS = ("fill_id", "broker_order_id", "quantity", "fill_price", "filled_at")
OPTIONAL_SECTION_COLUMNS = {
    "positions_csv": ("intent_id", "account_id", "position_qty"),
    "cash_csv": ("account_id", "cash_balance"),
    "journal_rows_csv": ("intent_id", "broker_order_id"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal live reconciliation artifact chain.")
    parser.add_argument("--manifest", required=True, help="JSON manifest path for reconciliation files.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as hard failures.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    return parser.parse_args(argv)


def parse_float(value: Any, *, field: str, row_no: int | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field}: expected number{_row_suffix(row_no)}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: invalid numeric value {value!r}{_row_suffix(row_no)}") from exc
    return number


def parse_datetime(value: Any, *, field: str, row_no: int | None = None) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: required ISO-8601 timestamp{_row_suffix(row_no)}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}: invalid ISO-8601 timestamp {value!r}{_row_suffix(row_no)}") from exc


def _row_suffix(row_no: int | None) -> str:
    return f" at row {row_no}" if row_no is not None else ""


def _validate_columns(header: list[str], required: tuple[str, ...], section: str) -> None:
    missing = [col for col in required if col not in header]
    if missing:
        raise ValueError(f"{section}: missing required columns: {', '.join(missing)}")


def _read_csv(
    path: Path,
    required: tuple[str, ...],
    section: str,
    *,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"{section}: file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        if not allow_empty:
            raise ValueError(f"{section}: no rows in file")
        return []
    _validate_columns(list(rows[0].keys()), required, section)
    return rows


def _required_fields(payload: dict[str, Any]) -> None:
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload or not payload[key]:
            raise ValueError(f"manifest: required key missing or empty: {key}")


def validate_reconciliation(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        _required_fields(manifest)
        asof = parse_datetime(manifest["asof"], field="manifest.asof", row_no=None)
        intents = _read_csv(Path(manifest["intents_csv"]), REQUIRED_INTENT_COLUMNS, "intents_csv")
        orders = _read_csv(Path(manifest["broker_orders_csv"]), REQUIRED_ORDER_COLUMNS, "broker_orders_csv", allow_empty=True)
        fills = _read_csv(Path(manifest["fills_csv"]), REQUIRED_FILL_COLUMNS, "fills_csv", allow_empty=True)

        optional_sections = {}
        for section_key, required_cols in OPTIONAL_SECTION_COLUMNS.items():
            path = manifest.get(section_key)
            if path:
                optional_sections[section_key] = _read_csv(Path(path), required_cols, section_key, allow_empty=True)
            else:
                warnings.append(f"{section_key}: optional section not provided; chain completeness checks will be partial.")

        intents_by_id: dict[str, dict[str, str]] = {}
        for i, row in enumerate(intents, start=1):
            iid = str(row.get("intent_id", "")).strip()
            if not iid:
                errors.append(f"intents_csv row {i}: missing intent_id")
                continue
            if iid in intents_by_id:
                warnings.append(f"intents_csv row {i}: duplicate intent_id={iid}")
            intents_by_id[iid] = row

            if row.get("approval_status", "").upper() not in ALLOWED_INTENT_APPROVAL_STATUS:
                errors.append(f"intents_csv row {i}: invalid approval_status={row.get('approval_status')!r}")
            if row.get("risk_status", "").upper() not in ALLOWED_RISK_STATUS:
                errors.append(f"intents_csv row {i}: invalid risk_status={row.get('risk_status')!r}")

            status = row.get("status", "").upper()
            if status not in ALLOWED_INTENT_STATUS:
                errors.append(f"intents_csv row {i}: invalid status={row.get('status')!r}")

            if row.get("approval_status", "").upper() == "APPROVED":
                if not str(row.get("approved_by", "")).strip():
                    errors.append(f"intents_csv row {i}: APPROVED intent missing approved_by")
                if "approved_at" not in row or not row.get("approved_at"):
                    errors.append(f"intents_csv row {i}: APPROVED intent missing approved_at")
                try:
                    parse_datetime(row.get("approved_at"), field="approved_at", row_no=i)
                except ValueError:
                    errors.append(f"intents_csv row {i}: APPROVED intent has invalid approved_at")
                if row.get("risk_status", "").upper() != "PASS":
                    warnings.append(
                        f"intents_csv row {i}: approval_status=APPROVED while risk_status={row.get('risk_status')}"
                    )
            if row.get("risk_status", "").upper() == "BLOCKED":
                warnings.append(f"intents_csv row {i}: risk_status=BLOCKED; runtime must fail closed.")

            asof_text = str(row.get("asof", "")).strip()
            if asof_text:
                intent_asof = parse_datetime(asof_text, field="intent.asof", row_no=i)
                if intent_asof > asof:
                    warnings.append(f"intents_csv row {i}: asof ({asof_text}) is after manifest asof")

        orders_by_intent: dict[str, list[dict[str, str]]] = {}
        order_qty_by_id: dict[str, float] = {}
        order_status_by_id: dict[str, str] = {}
        order_created_by_id: dict[str, datetime] = {}
        order_intent_map: dict[str, str] = {}
        for i, row in enumerate(orders, start=1):
            oid = str(row.get("broker_order_id", "")).strip()
            if not oid:
                errors.append(f"broker_orders_csv row {i}: missing broker_order_id")
                continue
            if row.get("intent_id") is None or not str(row.get("intent_id")).strip():
                errors.append(f"broker_orders_csv row {i}: missing intent_id")
                continue
            iid = str(row.get("intent_id")).strip()
            if iid not in intents_by_id:
                errors.append(f"broker_orders_csv row {i}: intent_id={iid} does not exist in intents_csv")
                continue
            status = str(row.get("status", "")).upper()
            if status not in ALLOWED_ORDER_STATUS:
                errors.append(f"broker_orders_csv row {i}: invalid status={row.get('status')!r}")

            qty = parse_float(row.get("quantity"), field="quantity", row_no=i)
            if qty < 0:
                errors.append(f"broker_orders_csv row {i}: quantity must be >= 0")
            order_qty_by_id[oid] = qty
            order_status_by_id[oid] = status
            order_created_by_id[oid] = parse_datetime(row.get("created_at"), field="created_at", row_no=i)
            order_intent_map[oid] = iid
            orders_by_intent.setdefault(iid, []).append(row)

        fill_qty_by_order: dict[str, float] = {}
        for i, row in enumerate(fills, start=1):
            fill_id = str(row.get("fill_id", "")).strip()
            if not fill_id:
                warnings.append(f"fills_csv row {i}: empty fill_id")
            oid = str(row.get("broker_order_id", "")).strip()
            if not oid:
                errors.append(f"fills_csv row {i}: missing broker_order_id")
                continue
            if oid not in order_intent_map:
                errors.append(f"fills_csv row {i}: broker_order_id={oid} does not exist in broker_orders_csv")
                continue

            qty = parse_float(row.get("quantity"), field="quantity", row_no=i)
            if qty <= 0:
                errors.append(f"fills_csv row {i}: quantity must be > 0")
            fill_qty_by_order[oid] = fill_qty_by_order.get(oid, 0.0) + qty

            fill_ts = parse_datetime(row.get("filled_at"), field="filled_at", row_no=i)
            order_ts = order_created_by_id.get(oid)
            if order_ts and (fill_ts - order_ts).total_seconds() < 0:
                warnings.append(f"fills_csv row {i}: fill timestamp precedes broker order created_at")

        # Integrity checks
        for intent_id, intent_row in intents_by_id.items():
            approval = intent_row.get("approval_status", "").upper()
            risk = intent_row.get("risk_status", "").upper()
            if approval == "APPROVED" and risk == "PASS":
                if not orders_by_intent.get(intent_id):
                    errors.append(f"intent_id={intent_id}: APPROVED intent has no broker order")
            elif approval == "APPROVED":
                warnings.append(f"intent_id={intent_id}: APPROVED despite risk_status={risk}")

        terminal_order_statuses = {"PARTIAL", "FILLED", "REJECTED", "FAILED", "ERROR"}
        for order_id, order_status in order_status_by_id.items():
            qty = order_qty_by_id[order_id]
            filled_qty = fill_qty_by_order.get(order_id, 0.0)
            iid = order_intent_map[order_id]
            if order_status in {"SUBMITTED", "REVIEWED"} and filled_qty > 0:
                warnings.append(
                    f"broker_order_id={order_id}: non-final order status {order_status} has fills; review execution semantics"
                )
            if order_status in terminal_order_statuses and filled_qty == 0:
                errors.append(
                    f"broker_order_id={order_id}: terminal order status {order_status} has no matching fills"
                )
            if filled_qty < qty:
                warnings.append(
                    f"broker_order_id={order_id}: filled_qty {filled_qty:.6f} < order_qty {qty:.6f} for intent_id={iid}"
                )
            if filled_qty > qty:
                errors.append(
                    f"broker_order_id={order_id}: filled_qty {filled_qty:.6f} exceeds order_qty {qty:.6f} for intent_id={iid}"
                )

        # Optional stage-completeness checks
        for section_key, section_rows in optional_sections.items():
            if not section_rows:
                continue
            if section_key == "positions_csv":
                for i, row in enumerate(section_rows, start=1):
                    iid = str(row.get("intent_id", "")).strip()
                    if iid and iid not in intents_by_id:
                        warnings.append(
                            f"positions_csv row {i}: intent_id={iid} not present in intents_csv"
                        )
            elif section_key == "cash_csv":
                for i, row in enumerate(section_rows, start=1):
                    account = str(row.get("account_id", "")).strip()
                    if not account:
                        errors.append(f"cash_csv row {i}: missing account_id")
            elif section_key == "journal_rows_csv":
                for i, row in enumerate(section_rows, start=1):
                    oid = str(row.get("broker_order_id", "")).strip()
                    if oid and oid not in order_intent_map:
                        warnings.append(f"journal_rows_csv row {i}: broker_order_id={oid} not in broker_orders_csv")

    except Exception as exc:  # pragma: no cover
        errors.append(str(exc))

    return errors, warnings


def run_validation(path: Path, strict: bool, as_json: bool) -> int:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object/dict")
    except Exception as exc:
        if as_json:
            print(json.dumps({"status": "failed", "errors": [str(exc)], "warnings": []}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}")
        return 1

    errors, warnings = validate_reconciliation(manifest)
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
        if errors or (strict and warnings):
            return 1
        return 0

    print(f"Validating manifest: {path}")
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
    return run_validation(Path(args.manifest).expanduser(), strict=args.strict, as_json=args.json)


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
