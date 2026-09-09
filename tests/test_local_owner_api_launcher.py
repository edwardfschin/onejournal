from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from scripts.web import run_local_owner_journal_api as launcher


class LocalOwnerApiLauncherTests(unittest.TestCase):
    def test_reporting_authorization_reaches_process_start_app_binding(self) -> None:
        broker_authorization = object()
        reporting_authorization = object()
        app = object()
        with (
            patch.object(
                launcher,
                "load_broker_current_financial_release_authorization",
                return_value=broker_authorization,
            ) as load_broker,
            patch.object(
                launcher,
                "load_reporting_release_authorization",
                return_value=reporting_authorization,
            ) as load_reporting,
            patch.object(
                launcher,
                "create_local_owner_journal_app",
                return_value=app,
            ) as create_app,
            patch.object(launcher.uvicorn, "run", Mock()) as run,
            patch.object(
                sys,
                "argv",
                [
                    "run_local_owner_journal_api.py",
                    "--db",
                    "/private/journal.duckdb",
                    "--broker-current-authorization",
                    "/private/current.json",
                    "--reporting-authorization",
                    "/private/report.json",
                    "--port",
                    "8765",
                ],
            ),
        ):
            self.assertEqual(launcher.main(), 0)

        load_broker.assert_called_once_with(Path("/private/current.json"))
        load_reporting.assert_called_once_with(Path("/private/report.json"))
        create_app.assert_called_once_with(
            journal_db_path=Path("/private/journal.duckdb"),
            broker_current_authorization=broker_authorization,
            reporting_authorization=reporting_authorization,
        )
        run.assert_called_once_with(
            app,
            host="127.0.0.1",
            port=8765,
            log_level="warning",
        )


if __name__ == "__main__":
    unittest.main()
