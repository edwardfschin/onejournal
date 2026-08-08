from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts/journal/fetch_schwab_raw_history_backfill.py"
SPEC = importlib.util.spec_from_file_location("onejournal_schwab_backfill_fetch", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


class SchwabRawHistoryBackfillFetchTests(unittest.TestCase):
    def test_protected_time_boundary_is_singapore_local(self) -> None:
        timezone = backfill.SINGAPORE_TZ

        self.assertTrue(backfill.protected_time_active(datetime(2026, 8, 6, 19, 50, tzinfo=timezone)))
        self.assertTrue(backfill.protected_time_active(datetime(2026, 8, 6, 20, 29, tzinfo=timezone)))
        self.assertFalse(backfill.protected_time_active(datetime(2026, 8, 6, 20, 30, tzinfo=timezone)))

    def test_raw_pair_state_distinguishes_resumable_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            paths = backfill.RawPairPaths(root / "orders.json", root / "transactions.json")
            self.assertEqual(backfill.raw_pair_state(paths), "missing")
            paths.orders.touch()
            self.assertEqual(backfill.raw_pair_state(paths), "partial")
            paths.transactions.touch()
            self.assertEqual(backfill.raw_pair_state(paths), "complete")

    def test_dry_run_has_no_live_side_effects(self) -> None:
        with patch.dict(backfill.os.environ, {}, clear=True):
            result = backfill.main(
                [
                    "--start",
                    "2025-01-01",
                    "--end",
                    "2025-02-01",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 0)

    def test_protected_time_blocks_live_before_token_or_network_access(self) -> None:
        original_now_sgt = backfill.now_sgt
        backfill.now_sgt = lambda: datetime(2026, 8, 6, 20, 0, tzinfo=backfill.SINGAPORE_TZ)
        try:
            with patch.dict(backfill.os.environ, {}, clear=True):
                result = backfill.main(["--start", "2025-01-01", "--end", "2025-01-01"])
        finally:
            backfill.now_sgt = original_now_sgt

        self.assertEqual(result, 1)

    def test_setup_failure_is_recorded_for_the_operator_report(self) -> None:
        report_rows: list[dict[str, object]] = []
        original_lock = backfill.single_operator_lock
        original_now_sgt = backfill.now_sgt

        @backfill.contextmanager
        def failing_lock(_token_path: Path):
            raise RuntimeError("lock already held")
            yield

        original_write_report = backfill.write_report
        backfill.single_operator_lock = failing_lock
        backfill.write_report = lambda _path, rows: report_rows.extend(rows)
        backfill.now_sgt = lambda: datetime(2026, 8, 6, 21, 0, tzinfo=backfill.SINGAPORE_TZ)
        try:
            with patch.dict(
                backfill.os.environ,
                {"ONEJOURNAL_SCHWAB_CLIENT_ID": "test-client"},
                clear=True,
            ):
                with redirect_stdout(StringIO()):
                    result = backfill.main(
                        [
                            "--start",
                            "2025-01-01",
                            "--end",
                            "2025-01-01",
                        ]
                    )
        finally:
            backfill.single_operator_lock = original_lock
            backfill.write_report = original_write_report
            backfill.now_sgt = original_now_sgt

        self.assertEqual(result, 1)
        self.assertEqual(report_rows[0]["status"], "setup_failed")
        self.assertIn("lock already held", str(report_rows[0]["error"]))

    def test_raw_paths_preserve_the_window_date_range(self) -> None:
        window = backfill.planner.FetchWindow(date(2025, 1, 1), date(2025, 1, 30))
        paths = backfill.raw_pair_paths(date(2026, 8, 6), "hash", window)

        self.assertIn("2026-08-06/orders_all/hash__2025-01-01__2025-01-30.json", str(paths.orders))
        self.assertIn("2026-08-06/transactions/hash__2025-01-01__2025-01-30.json", str(paths.transactions))

    def test_legacy_configuration_is_rejected_before_dry_run(self) -> None:
        with patch.dict(backfill.os.environ, {"CLIENT_ID": "legacy"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "CLIENT_ID"):
                backfill.main(
                    [
                        "--start",
                        "2025-01-01",
                        "--end",
                        "2025-01-01",
                        "--dry-run",
                    ]
                )

    def test_onebot_token_path_is_rejected_before_dry_run(self) -> None:
        with patch.dict(backfill.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OneBot token path"):
                backfill.main(
                    [
                        "--start",
                        "2025-01-01",
                        "--end",
                        "2025-01-01",
                        "--token-path",
                        str(Path.home() / ".onebot/tokens/schwab_tokens.json"),
                        "--dry-run",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
