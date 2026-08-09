from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import importlib.util

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "liv" / "validate_intent_event.py"
SPEC = importlib.util.spec_from_file_location("validate_liv_intent_event", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class LivIntentEventValidatorTests(unittest.TestCase):
    def make_payload(self, *, status: str = "APPROVED") -> dict[str, object]:
        return {
            "intent_id": "22222222-2222-4222-b222-222222222222",
            "source_signal_id": "sig-001",
            "account_id": "ACCT-001",
            "broker": "SCHWAB",
            "symbol": "SPY",
            "asset_class": "OPTION",
            "side": "BUY",
            "quantity": 1.0,
            "order_type": "LIMIT",
            "limit_price": 500.0,
            "strategy_id": "options-income",
            "created_at": "2026-08-10T01:00:00Z",
            "risk_status": "PASS",
            "approval_status": status,
            "approved_by": "owner-001",
            "approved_at": "2026-08-10T01:05:00Z",
            "pilot_version": "liv-pilot-001",
            "idempotency_key": "idem-001",
            "status": "NEW",
        }

    def test_validate_valid_payload(self) -> None:
        payload = self.make_payload()
        errors, warnings = validator.validate_intent_payload(payload)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_reject_invalid_uuid(self) -> None:
        payload = self.make_payload()
        payload["intent_id"] = "not-a-uuid"
        errors, warnings = validator.validate_intent_payload(payload)
        self.assertTrue(any("intent_id" in issue for issue in errors))
        self.assertEqual(warnings, [])

    def test_approved_without_approver_is_error(self) -> None:
        payload = self.make_payload()
        payload["approval_status"] = "APPROVED"
        payload["approved_by"] = ""
        errors, warnings = validator.validate_intent_payload(payload)
        self.assertTrue(any("approved_by" in issue for issue in errors))
        self.assertEqual(warnings, [])

    def test_run_command_with_warning_in_strict_mode(self) -> None:
        payload = self.make_payload()
        payload["risk_status"] = "BLOCKED"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(payload, tmp)
            path = tmp.name

        self.assertEqual(validator.main(["--payload", path]), 0)
        self.assertEqual(validator.main(["--payload", path, "--strict"]), 1)

    def test_run_command_with_valid_payload(self) -> None:
        payload = self.make_payload(status="PENDING")
        payload.pop("approved_by", None)
        payload.pop("approved_at", None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(payload, tmp)
            path = tmp.name

        self.assertEqual(validator.main(["--payload", path]), 0)


if __name__ == "__main__":
    unittest.main()
