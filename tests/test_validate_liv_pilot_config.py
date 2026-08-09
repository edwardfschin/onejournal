from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
import json

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "liv" / "validate_pilot_config.py"
SPEC = importlib.util.spec_from_file_location("validate_liv_pilot_config", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class LivPilotConfigValidatorTests(unittest.TestCase):
    def make_config(self, *, status: str = "disabled", environment: str = "paper") -> dict[str, object]:
        return {
            "pilot": {
                "version": 1,
                "policy_id": "liv-pilot-001",
                "status": status,
                "environment": environment,
                "effective_from_utc": "2026-08-10T00:00:00Z",
                "kill_switch_required": True,
                "force_paper_first": True,
                "kill_switch_env_var": "ONEJOURNAL_LIV_KILL_SWITCH",
                "allow_list": {
                    "accounts": [
                        {
                            "id": "ACCT-001",
                            "currency": "USD",
                            "max_notional": 2500.0,
                            "max_daily_loss_limit": 250.0,
                            "max_orders_per_day": 4,
                        }
                    ],
                    "symbols": [
                        {
                            "symbol": "SPY",
                            "max_qty": 1,
                        }
                    ],
                    "strategies": ["options-income"],
                },
                "risk_limits": {
                    "max_notional_per_order": 500.0,
                    "max_notional_daily": 1500.0,
                    "max_quantity_per_order": 2,
                    "max_position_delta_notional": 2500.0,
                    "min_market_hours_only": True,
                    "allowed_sessions": ["RTH"],
                },
                "schedule": {
                    "timezone": "America/New_York",
                    "enabled_windows_utc": [
                        {
                            "start_time": "13:30",
                            "end_time": "20:00",
                        }
                    ],
                },
                "controls": {
                    "duplicate_prevention": {
                        "require_idempotency_key": True,
                        "duplicate_tolerance_seconds": 120,
                    },
                    "approvals": {
                        "requires_two_step_approval": False,
                        "default_ttl_minutes": 120,
                    },
                },
            }
        }

    def test_validate_valid_pilot_config(self) -> None:
        errors, warnings = validator.validate_pilot_config(self.make_config())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_reject_invalid_status(self) -> None:
        bad = self.make_config(status="manual")
        errors, warnings = validator.validate_pilot_config(bad)
        self.assertEqual(len(errors), 1)
        self.assertEqual(warnings, [])

    def test_reject_active_live_without_live_environment(self) -> None:
        bad = self.make_config(status="live", environment="paper")
        errors, warnings = validator.validate_pilot_config(bad)
        self.assertEqual(warnings, [])
        self.assertIn("pilot.status=live requires pilot.environment=live", errors[0])

    def test_live_with_force_paper_first_raises_warning(self) -> None:
        live = self.make_config(status="live", environment="live")
        errors, warnings = validator.validate_pilot_config(live)
        self.assertEqual(errors, [])
        self.assertTrue(any("force_paper_first" in issue for issue in warnings))

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(live, tmp)
            tmp_path = tmp.name

        self.assertEqual(validator.main(["--config", tmp_path]), 0)
        self.assertEqual(validator.main(["--config", tmp_path, "--strict"]), 1)

    def test_run_command_with_valid_config(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(self.make_config(status="disabled", environment="paper"), tmp)
            path = tmp.name

        status = validator.main(["--config", path])
        self.assertEqual(status, 0)

        status_strict = validator.main(["--config", path, "--strict"])
        self.assertEqual(status_strict, 0)


if __name__ == "__main__":
    unittest.main()
