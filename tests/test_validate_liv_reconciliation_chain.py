from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
import importlib.util

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "liv" / "validate_reconciliation_chain.py"
SPEC = importlib.util.spec_from_file_location("validate_liv_reconciliation_chain", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class LivReconciliationValidatorTests(unittest.TestCase):
    def make_csv(self, rows: list[dict[str, object]], headers: list[str], *, suffix: str) -> str:
        tmp = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        with tmp as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return tmp.name

    def make_manifest(
        self,
        *,
        intents: list[dict[str, object]],
        orders: list[dict[str, object]],
        fills: list[dict[str, object]],
        positions: list[dict[str, object]] | None = None,
        cash: list[dict[str, object]] | None = None,
        journal: list[dict[str, object]] | None = None,
    ) -> str:
        intents_path = self.make_csv(intents, ["intent_id", "account_id", "broker", "status", "risk_status", "approval_status", "approved_by", "approved_at", "asof"], suffix=".csv")
        orders_path = self.make_csv(
            orders,
            ["broker_order_id", "intent_id", "status", "quantity", "created_at"],
            suffix=".csv",
        )
        fills_path = self.make_csv(
            fills,
            ["fill_id", "broker_order_id", "quantity", "fill_price", "filled_at"],
            suffix=".csv",
        )
        manifest = {
            "intents_csv": intents_path,
            "broker_orders_csv": orders_path,
            "fills_csv": fills_path,
            "asof": "2026-08-10T12:00:00Z",
        }
        if positions is not None:
            manifest["positions_csv"] = self.make_csv(
                positions,
                ["intent_id", "account_id", "position_qty"],
                suffix=".csv",
            )
        if cash is not None:
            manifest["cash_csv"] = self.make_csv(
                cash,
                ["account_id", "cash_balance"],
                suffix=".csv",
            )
        if journal is not None:
            manifest["journal_rows_csv"] = self.make_csv(
                journal,
                ["intent_id", "broker_order_id"],
                suffix=".csv",
            )
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        with tmp as fh:
            json.dump(manifest, fh)
        return tmp.name

    def test_validate_reconciliation_chain_ok(self) -> None:
        manifest_path = self.make_manifest(
            intents=[
                {
                    "intent_id": "11111111-1111-4111-b111-111111111111",
                    "account_id": "ACCT-001",
                    "broker": "SCHWAB",
                    "status": "FILLED",
                    "risk_status": "PASS",
                    "approval_status": "APPROVED",
                    "approved_by": "owner",
                    "approved_at": "2026-08-10T11:00:00Z",
                    "asof": "2026-08-10T11:30:00Z",
                }
            ],
            orders=[
                {
                    "broker_order_id": "ord-001",
                    "intent_id": "11111111-1111-4111-b111-111111111111",
                    "status": "FILLED",
                    "quantity": 2,
                    "created_at": "2026-08-10T11:05:00Z",
                }
            ],
            fills=[
                {
                    "fill_id": "fill-001",
                    "broker_order_id": "ord-001",
                    "quantity": 2,
                    "fill_price": 1.23,
                    "filled_at": "2026-08-10T11:10:00Z",
                }
            ],
            positions=[{"intent_id": "11111111-1111-4111-b111-111111111111", "account_id": "ACCT-001", "position_qty": 2}],
            cash=[{"account_id": "ACCT-001", "cash_balance": 1000}],
            journal=[{"intent_id": "11111111-1111-4111-b111-111111111111", "broker_order_id": "ord-001"}],
        )
        errors, warnings = validator.validate_reconciliation(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_approved_intent_without_order_fails(self) -> None:
        manifest_path = self.make_manifest(
            intents=[
                {
                    "intent_id": "22222222-2222-4222-b222-222222222222",
                    "account_id": "ACCT-002",
                    "broker": "SCHWAB",
                    "status": "APPROVED",
                    "risk_status": "PASS",
                    "approval_status": "APPROVED",
                    "approved_by": "owner",
                    "approved_at": "2026-08-10T11:00:00Z",
                    "asof": "2026-08-10T11:30:00Z",
                }
            ],
            orders=[],
            fills=[],
        )
        errors, warnings = validator.validate_reconciliation(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
        self.assertTrue(any("no broker order" in issue for issue in errors))
        self.assertIsInstance(warnings, list)

    def test_orphan_order_fails(self) -> None:
        manifest_path = self.make_manifest(
            intents=[
                {
                    "intent_id": "11111111-1111-4111-b111-111111111111",
                    "account_id": "ACCT-001",
                    "broker": "SCHWAB",
                    "status": "APPROVED",
                    "risk_status": "PASS",
                    "approval_status": "APPROVED",
                    "approved_by": "owner",
                    "approved_at": "2026-08-10T11:00:00Z",
                    "asof": "2026-08-10T11:30:00Z",
                }
            ],
            orders=[
                {
                    "broker_order_id": "ord-001",
                    "intent_id": "missing-intent",
                    "status": "SUBMITTED",
                    "quantity": 1,
                    "created_at": "2026-08-10T11:05:00Z",
                }
            ],
            fills=[],
        )
        errors, _warnings = validator.validate_reconciliation(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
        self.assertTrue(any("does not exist in intents_csv" in issue for issue in errors))

    def test_terminal_order_without_fill_fails(self) -> None:
        manifest_path = self.make_manifest(
            intents=[
                {
                    "intent_id": "33333333-3333-4333-b333-333333333333",
                    "account_id": "ACCT-003",
                    "broker": "SCHWAB",
                    "status": "FAILED",
                    "risk_status": "PASS",
                    "approval_status": "PENDING",
                    "asof": "2026-08-10T11:30:00Z",
                }
            ],
            orders=[
                {
                    "broker_order_id": "ord-002",
                    "intent_id": "33333333-3333-4333-b333-333333333333",
                    "status": "FAILED",
                    "quantity": 1,
                    "created_at": "2026-08-10T11:05:00Z",
                }
            ],
            fills=[],
        )
        errors, _warnings = validator.validate_reconciliation(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
        self.assertTrue(any("terminal order status" in issue for issue in errors))

    def test_strict_warning_promotes_to_failure(self) -> None:
        manifest_path = self.make_manifest(
            intents=[
                {
                    "intent_id": "44444444-4444-4444-b444-444444444444",
                    "account_id": "ACCT-004",
                    "broker": "SCHWAB",
                    "status": "APPROVED",
                    "risk_status": "BLOCKED",
                    "approval_status": "APPROVED",
                    "approved_by": "owner",
                    "approved_at": "2026-08-10T11:00:00Z",
                    "asof": "2026-08-10T11:30:00Z",
                }
            ],
            orders=[],
            fills=[],
        )
        # risk_status=BLOCKED is warning with approved intent
        self.assertEqual(validator.main(["--manifest", manifest_path]), 0)
        self.assertEqual(validator.main(["--manifest", manifest_path, "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
