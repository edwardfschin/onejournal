from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts/journal/plan_schwab_raw_history_backfill.py"
SPEC = importlib.util.spec_from_file_location("onejournal_schwab_backfill_planner", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
planner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = planner
SPEC.loader.exec_module(planner)


class SchwabRawHistoryBackfillPlannerTests(unittest.TestCase):
    def test_default_chunk_is_thirty_days(self) -> None:
        args = planner.parse_args(["--start", "2025-01-01", "--end", "2025-01-01"])

        self.assertEqual(args.chunk_days, 30)

    def test_inclusive_windows_are_contiguous_and_bounded(self) -> None:
        windows = planner.plan_windows(date(2025, 1, 1), date(2025, 2, 1), 30)

        self.assertEqual(
            windows,
            [
                planner.FetchWindow(date(2025, 1, 1), date(2025, 1, 30)),
                planner.FetchWindow(date(2025, 1, 31), date(2025, 2, 1)),
            ],
        )
        self.assertEqual([window.days for window in windows], [30, 2])

    def test_invalid_range_and_chunk_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "on or after"):
            planner.plan_windows(date(2025, 2, 1), date(2025, 1, 1), 30)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            planner.plan_windows(date(2025, 1, 1), date(2025, 1, 1), 0)

    def test_api_estimate_keeps_account_discovery_explicit(self) -> None:
        self.assertEqual(
            planner.estimated_api_calls(3),
            {
                "account_lookup": 1,
                "orders": 3,
                "transactions": 3,
                "without_account_lookup": 6,
                "with_account_lookup": 7,
            },
        )

    def test_documented_example_is_offline_and_complete(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--start",
                "2020-01-01",
                "--end",
                "2026-06-11",
                "--chunk-days",
                "30",
            ],
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NETWORK_ACCESS               : disabled", result.stdout)
        self.assertIn("TOKEN_ACCESS                 : disabled", result.stdout)
        self.assertIn("FILESYSTEM_WRITE              : disabled", result.stdout)
        self.assertIn("DUCKDB_WRITE                  : disabled", result.stdout)
        self.assertIn("WINDOWS_TOTAL                : 79", result.stdout)
        self.assertIn("ESTIMATED_GETS_WITH_DISCOVERY: 159", result.stdout)
        self.assertIn("WINDOW 079 : 2026-05-29 to 2026-06-11 (14 days)", result.stdout)
        self.assertIn("STATUS                       : OK", result.stdout)

    def test_one_day_window_uses_singular_label(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--start",
                "2025-01-01",
                "--end",
                "2025-01-01",
            ],
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WINDOW 001 : 2025-01-01 to 2025-01-01 (1 day)", result.stdout)


if __name__ == "__main__":
    unittest.main()
