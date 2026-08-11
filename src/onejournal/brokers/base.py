"""Read-only broker adapter contract for OneJournal.

This module defines the standard interface that every broker/import adapter
must follow.

It does not contain Schwab endpoint logic, IBKR connection logic, OAuth logic,
dashboard logic, DuckDB writes, or order placement.

Adapters convert source-specific raw data into OneJournal broker-normalized
records from onejournal.brokers.normalized.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from datetime import date
from typing import Generic, TypeVar

from onejournal.brokers.normalized import (
    NormalizedAccount,
    NormalizedFill,
    NormalizedOrder,
    NormalizedPosition,
    NormalizedQuote,
    NormalizedTransaction,
)

T = TypeVar("T")


@dataclass(frozen=True)
class BrokerAdapterResult(Generic[T]):
    """Standard result wrapper returned by broker adapter methods.

    The result keeps every adapter response traceable and easy to validate.

    Attributes
    ----------
    source_broker:
        Broker/import source name, for example schwab, ibkr, or manual_csv.
    asof:
        Market date used for the fetch/import.
    records:
        Normalized records returned by the adapter.
    raw_paths:
        Source raw file paths used or written by the adapter.
    warnings:
        Non-fatal issues.
    errors:
        Fatal or blocking issues. A result with errors should not be treated
        as clean.
    """

    source_broker: str
    asof: date
    records: list[T] = field(default_factory=list)
    raw_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when the adapter result has no errors."""

        return not self.errors

    @property
    def record_count(self) -> int:
        """Return number of normalized records."""

        return len(self.records)


class BrokerAdapter(ABC):
    """Base read-only broker/import adapter.

    Subclasses should implement the methods supported by that source.

    The base implementation returns an explicit unsupported result rather than
    silently failing. This makes unsupported broker capabilities visible in
    logs, tests, and operator checks.
    """

    source_broker: str = "unknown"

    def fetch_accounts(self, asof: date) -> BrokerAdapterResult[NormalizedAccount]:
        """Fetch/import account snapshots for the given market date."""

        return self._unsupported("fetch_accounts", asof)

    def fetch_orders(self, asof: date) -> BrokerAdapterResult[NormalizedOrder]:
        """Fetch/import order records for the given market date."""

        return self._unsupported("fetch_orders", asof)

    def fetch_fills(self, asof: date) -> BrokerAdapterResult[NormalizedFill]:
        """Fetch/import execution fills for the given market date."""

        return self._unsupported("fetch_fills", asof)

    def fetch_positions(self, asof: date) -> BrokerAdapterResult[NormalizedPosition]:
        """Fetch/import position snapshots for the given market date."""

        return self._unsupported("fetch_positions", asof)

    def fetch_quotes(
        self,
        asof: date,
        instrument_keys: tuple[str, ...],
    ) -> BrokerAdapterResult[NormalizedQuote]:
        """Fetch read-only quotes for explicit broker-independent instruments.

        The base adapter intentionally does not perform symbol discovery or
        provider fallback. A provider adapter must resolve every requested
        instrument explicitly and report unsupported or unentitled records.
        """

        del instrument_keys
        return self._unsupported("fetch_quotes", asof)

    def fetch_transactions(
        self,
        asof: date,
    ) -> BrokerAdapterResult[NormalizedTransaction]:
        """Fetch/import accounting transactions for the given market date."""

        return self._unsupported("fetch_transactions", asof)

    def _unsupported(self, method_name: str, asof: date) -> BrokerAdapterResult:
        """Return a standard unsupported-method result."""

        return BrokerAdapterResult(
            source_broker=self.source_broker,
            asof=asof,
            records=[],
            warnings=[],
            errors=[
                f"{self.__class__.__name__}.{method_name} is not supported yet"
            ],
        )
