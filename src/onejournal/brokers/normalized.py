"""Broker-normalized record definitions for OneJournal.

These records form the broker-independent contract between raw broker/import
data and the journal layer.

The broker adapters are responsible for converting Schwab, IBKR, manual CSV,
or any future broker source into these normalized records.

This module is read-only by design. It does not fetch data, write data, or
place orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class NormalizedAccount:
    """Broker-independent account snapshot."""

    account_uid: str
    source_broker: str
    source_account_id: str
    account_label: str
    account_type: str
    currency: str
    asof: date
    fetched_at: datetime
    raw_path: str | None = None

    buying_power: Decimal | None = None
    cash_balance: Decimal | None = None
    net_liquidation_value: Decimal | None = None
    maintenance_requirement: Decimal | None = None
    initial_requirement: Decimal | None = None
    day_trade_buying_power: Decimal | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedOrder:
    """Broker-independent order record.

    An order is not the same as a trade episode.
    One order may have zero, one, or many fills.
    """

    order_uid: str
    source_broker: str
    source_account_id: str
    source_order_id: str
    asof: date
    order_status: str
    order_type: str
    time_in_force: str
    asset_class: str
    symbol: str
    side: str
    quantity: Decimal
    created_at: datetime
    fetched_at: datetime
    raw_path: str | None = None

    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    cancelled_at: datetime | None = None
    replaced_by_order_id: str | None = None
    parent_order_id: str | None = None
    broker_strategy_type: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedFill:
    """Broker-independent execution fill.

    P&L should be based on actual fills and broker-confirmed activity,
    not theoretical signal output.
    """

    fill_uid: str
    source_broker: str
    source_account_id: str
    source_fill_id: str
    source_order_id: str | None
    episode_group_id: str | None
    asof: date
    filled_at: datetime
    asset_class: str
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    commission: Decimal
    fees: Decimal
    currency: str
    fetched_at: datetime
    raw_path: str | None = None

    option_symbol: str | None = None
    underlying_symbol: str | None = None
    option_type: str | None = None
    expiry: date | None = None
    strike: Decimal | None = None
    multiplier: Decimal | None = None
    open_close: str | None = None
    execution_venue: str | None = None
    liquidity_flag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedPosition:
    """Broker-independent position snapshot."""

    position_uid: str
    source_broker: str
    source_account_id: str
    asof: date
    asset_class: str
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal
    currency: str
    fetched_at: datetime
    raw_path: str | None = None

    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    delta: Decimal | None = None
    beta_weighted_delta: Decimal | None = None
    option_symbol: str | None = None
    underlying_symbol: str | None = None
    option_type: str | None = None
    expiry: date | None = None
    strike: Decimal | None = None
    multiplier: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedTransaction:
    """Broker-independent accounting transaction.

    Examples include cash movements, assignment, expiry, dividends, fees,
    option exercise, and broker adjustment records.
    """

    transaction_uid: str
    source_broker: str
    source_account_id: str
    source_transaction_id: str
    asof: date
    transaction_at: datetime
    transaction_type: str
    amount: Decimal
    currency: str
    fetched_at: datetime
    raw_path: str | None = None

    symbol: str | None = None
    asset_class: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    commission: Decimal | None = None
    fees: Decimal | None = None
    description: str | None = None
    linked_order_id: str | None = None
    linked_fill_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedQuote:
    """Broker-independent top-of-book quote evidence.

    A quote is market-data evidence, not an account position and not an
    automatically valid valuation mark. ``onejournal.market_data`` validates
    its timestamps, entitlement, session, delay mode, and prices at the time a
    caller requests a mark.

    ``connection_uid`` is an opaque local identifier for the user-owned broker
    connection whose entitlement produced the quote. It must not contain an
    account number, token, username, or other credential.
    """

    quote_uid: str
    provider: str
    connection_uid: str
    instrument_key: str
    provider_instrument_id: str
    symbol: str
    asset_class: str
    currency: str
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    provider_quote_at: datetime
    received_at: datetime
    market_session: str
    data_mode: str
    entitlement_status: str
    asof: date
    raw_path: str
    raw_sha256: str
    adapter_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
