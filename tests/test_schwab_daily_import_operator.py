from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.journal import run_schwab_daily_import as operator


class SchwabDailyImportOperatorTests(unittest.TestCase):
    def test_lifecycle_only_day_reaches_guarded_database_import(self) -> None:
        commands: list[list[str]] = []

        def fake_run(cmd: list[str]) -> None:
            commands.append(cmd)
            if any(
                part.endswith("convert_schwab_orders_json_to_normalized_fills.py")
                for part in cmd
            ):
                output = Path(cmd[cmd.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("asof,source_fill_id\n", encoding="utf-8")
            if any(
                part.endswith("convert_schwab_transactions_json_to_normalized_fills.py")
                for part in cmd
            ):
                output = Path(cmd[cmd.index("--output") + 1])
                lifecycle = Path(cmd[cmd.index("--lifecycle-events") + 1])
                lifecycle_legs = Path(cmd[cmd.index("--lifecycle-event-legs") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("asof,source_fill_id\n", encoding="utf-8")
                lifecycle.write_text(
                    "event_uid,asof\nevent:expiration,2026-06-02\n",
                    encoding="utf-8",
                )
                lifecycle_legs.write_text(
                    "event_leg_uid,event_uid\nevent:expiration:item:0,event:expiration\n",
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as root:
            argv = [
                "run_schwab_daily_import.py",
                "--asof",
                "2026-06-02",
                "--orders",
                "orders.json",
                "--transactions",
                "transactions.json",
                "--db",
                str(Path(root) / "journal.duckdb"),
                "--import-db",
            ]
            output = StringIO()
            with (
                patch.object(operator, "PROJECT_DIR", Path(root)),
                patch.object(operator, "run", side_effect=fake_run),
                patch.object(sys, "argv", argv),
                redirect_stdout(output),
            ):
                self.assertEqual(operator.main(), 0)

        self.assertIn("LIFECYCLE-ONLY RESULT", output.getvalue())
        import_commands = [
            cmd
            for cmd in commands
            if any(part.endswith("import_journal_to_db.py") for part in cmd)
        ]
        self.assertEqual(len(import_commands), 1)
        self.assertIn("--lifecycle-events", import_commands[0])
        self.assertIn("--lifecycle-event-legs", import_commands[0])
        self.assertFalse(
            any(
                any(
                    part.endswith("reconcile_schwab_orders_transactions.py")
                    for part in cmd
                )
                for cmd in commands
            )
        )


if __name__ == "__main__":
    unittest.main()
