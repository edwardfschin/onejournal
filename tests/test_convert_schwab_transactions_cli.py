from __future__ import annotations

import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.journal.convert_schwab_transactions_json_to_normalized_fills import main as convert_main


class ConvertSchwabTransactionsCliTests(TestCase):
    def _run_cli(self, payload: list[dict], asof: str) -> str:
        with tempfile.TemporaryDirectory() as root:
            input_path = Path(root) / "input.json"
            output_path = Path(root) / "normalized.csv"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            stdout = StringIO()
            argv = [
                "convert_schwab_transactions_json_to_normalized_fills.py",
                "--asof",
                asof,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ]
            with patch.object(sys, "argv", argv):
                with redirect_stdout(stdout):
                    convert_main()

            return stdout.getvalue()

    def test_cli_reports_unsupported_activity_counts(self) -> None:
        payload = [
            {
                "type": "TRADE",
                "status": "VALID",
                "activityType": "ASSIGNMENT",
                "activityId": "A1",
                "tradeDate": "2026-07-01T12:00:00-05:00",
                "transferItems": [
                    {"amount": 1, "instrument": {"assetType": "EQUITY", "symbol": "AAPL"}}
                ],
            },
            {
                "type": "TRANSFER",
                "status": "VALID",
                "tradeDate": "2026-07-01T12:00:00-05:00",
                "transferItems": [
                    {"amount": 1, "instrument": {"assetType": "EQUITY", "symbol": "MSFT"}}
                ],
            },
        ]
        text = self._run_cli(payload, "2026-07-01")

        self.assertIn("UNSUPPORTED_ACTIVITY_COUNTS:", text)
        self.assertIn("activityType:ASSIGNMENT", text)
        self.assertIn("UNSUPPORTED_RECORD_COUNTS:", text)
        self.assertIn("record_type:TRANSFER", text)
        self.assertIn("UNSUPPORTED_ITEMS  : 2", text)

    def test_cli_skips_unsupported_sections_when_not_present(self) -> None:
        payload = [
            {
                "type": "TRADE",
                "status": "VALID",
                "activityId": "A2",
                "tradeDate": "2026-07-01T12:00:00-05:00",
                "orderId": "ORD-1",
                "positionId": "POS-1",
                "accountNumber": "ACCT",
                "transferItems": [
                    {
                        "amount": 2,
                        "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                        "positionEffect": "OPENING",
                        "price": 10,
                        "cost": 20,
                    }
                ],
            }
        ]
        text = self._run_cli(payload, "2026-07-01")

        self.assertIn("UNSUPPORTED_ITEMS  : 0", text)
        self.assertNotIn("UNSUPPORTED_ACTIVITY_COUNTS:", text)
        self.assertNotIn("UNSUPPORTED_ASSET_COUNTS:", text)
        self.assertNotIn("UNSUPPORTED_RECORD_COUNTS:", text)
