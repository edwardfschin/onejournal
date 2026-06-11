"""Manual CSV broker adapter for OneJournal.

This adapter is the safest first adapter because it does not connect to any
broker API.

Current status:
- read-only
- no CSV parsing yet
- no data writes
- no order placement
- returns explicit unsupported-method results through BrokerAdapter

Future role:
- read manual CSV exports from data/raw/manual_imports/
- normalize rows into OneJournal broker-normalized records
"""

from __future__ import annotations

from pathlib import Path

from onejournal.brokers.base import BrokerAdapter


class ManualCsvAdapter(BrokerAdapter):
    """Read-only adapter for manually supplied broker/import CSV files."""

    source_broker = "manual_csv"

    def __init__(self, input_dir: str | Path = "data/raw/manual_imports") -> None:
        self.input_dir = Path(input_dir)

    def source_description(self) -> str:
        """Return a simple human-readable adapter description."""

        return f"{self.source_broker} input_dir={self.input_dir}"
