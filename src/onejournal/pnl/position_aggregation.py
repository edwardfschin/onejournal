"""Fail-closed PNL-03 strategy and same-currency portfolio summaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal

from onejournal.pnl.position_valuation import (
    CanonicalPositionValuation,
    PositionValuationRun,
)


class PositionAggregationError(ValueError):
    """Raised when a requested valuation aggregation scope is malformed."""


_UID_RE = re.compile(r"[^\x00-\x1f\x7f]{1,256}")


def _currency(value: str) -> str:
    currency = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise PositionAggregationError("currency must be an explicit three-letter code")
    return currency


@dataclass(frozen=True)
class StrategyValuationScope:
    """Explicit leg membership for one presentation-only multi-leg strategy."""

    strategy_uid: str
    currency: str
    instrument_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_uid, str) or not _UID_RE.fullmatch(
            self.strategy_uid.strip()
        ):
            raise PositionAggregationError("strategy_uid is required and invalid")
        if len(self.instrument_keys) < 2:
            raise PositionAggregationError("a multi-leg strategy requires at least two legs")
        keys = tuple(item.strip() for item in self.instrument_keys)
        if any(not item or not _UID_RE.fullmatch(item) for item in keys):
            raise PositionAggregationError("instrument_keys are required and invalid")
        if len(set(keys)) != len(keys):
            raise PositionAggregationError("strategy scope contains duplicate instrument keys")
        object.__setattr__(self, "strategy_uid", self.strategy_uid.strip())
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "instrument_keys", keys)


@dataclass(frozen=True)
class StrategyValuationSummary:
    strategy_uid: str
    valuation_run_uid: str
    currency: str
    evaluated_at_utc: str
    included_count: int
    valid_count: int
    unavailable_count: int
    reconciliation_pending_count: int
    missing_count: int
    status: Literal["valid", "unavailable"]
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioCurrencyValuationSummary:
    valuation_run_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    currency: str
    evaluated_at_utc: str
    included_count: int
    valid_count: int
    unavailable_count: int
    reconciliation_pending_count: int
    status: Literal["valid", "unavailable"]
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    reason_codes: tuple[str, ...]


def _evaluate_positions(
    positions: tuple[CanonicalPositionValuation, ...],
) -> tuple[int, int, int, Decimal | None, Decimal | None, tuple[str, ...]]:
    valid_count = 0
    unavailable_count = 0
    pending_count = 0
    market_value = Decimal("0")
    unrealized_pnl = Decimal("0")
    reasons: set[str] = set()
    for position in positions:
        if position.status == "valid":
            if position.market_value is None or position.unrealized_pnl is None:
                unavailable_count += 1
                reasons.add("position_missing_financial_value")
                continue
            valid_count += 1
            market_value += position.market_value
            unrealized_pnl += position.unrealized_pnl
        elif position.status == "unavailable":
            unavailable_count += 1
            reasons.add("position_unavailable")
        elif position.status == "reconciliation_pending":
            pending_count += 1
            reasons.add("position_reconciliation_pending")
        else:
            raise PositionAggregationError("position has an unsupported valuation status")
    if valid_count != len(positions):
        return (
            valid_count,
            unavailable_count,
            pending_count,
            None,
            None,
            tuple(sorted(reasons)),
        )
    return valid_count, unavailable_count, pending_count, market_value, unrealized_pnl, ()


def build_strategy_valuation_summary(
    run: PositionValuationRun,
    *,
    scope: StrategyValuationScope,
) -> StrategyValuationSummary:
    """Return a strategy total only when every explicitly declared leg is valid."""

    by_key = {item.identity.key: item for item in run.positions}
    selected: list[CanonicalPositionValuation] = []
    missing_count = 0
    for key in scope.instrument_keys:
        position = by_key.get(key)
        if position is None:
            missing_count += 1
            continue
        if position.identity.currency != scope.currency:
            raise PositionAggregationError(
                "strategy scope currency does not match an included instrument"
            )
        selected.append(position)
    valid_count, unavailable_count, pending_count, market_value, unrealized_pnl, reasons = (
        _evaluate_positions(tuple(selected))
    )
    if missing_count:
        reasons = tuple(sorted(set(reasons) | {"strategy_leg_missing"}))
    status: Literal["valid", "unavailable"] = (
        "valid"
        if missing_count == 0 and valid_count == len(scope.instrument_keys)
        else "unavailable"
    )
    if status != "valid":
        market_value = None
        unrealized_pnl = None
    return StrategyValuationSummary(
        strategy_uid=scope.strategy_uid,
        valuation_run_uid=run.valuation_run_uid,
        currency=scope.currency,
        evaluated_at_utc=run.evaluated_at.isoformat(),
        included_count=len(scope.instrument_keys),
        valid_count=valid_count,
        unavailable_count=unavailable_count,
        reconciliation_pending_count=pending_count,
        missing_count=missing_count,
        status=status,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        reason_codes=reasons,
    )


def build_portfolio_currency_valuation_summary(
    run: PositionValuationRun,
    *,
    currency: str,
) -> PortfolioCurrencyValuationSummary:
    """Return one same-currency account subtotal without partial-value fallback."""

    currency = _currency(currency)
    selected = tuple(item for item in run.positions if item.identity.currency == currency)
    if not selected:
        return PortfolioCurrencyValuationSummary(
            valuation_run_uid=run.valuation_run_uid,
            source_broker=run.source_broker,
            connection_uid=run.connection_uid,
            source_account_id=run.source_account_id,
            currency=currency,
            evaluated_at_utc=run.evaluated_at.isoformat(),
            included_count=0,
            valid_count=0,
            unavailable_count=0,
            reconciliation_pending_count=0,
            status="unavailable",
            market_value=None,
            unrealized_pnl=None,
            reason_codes=("no_positions_in_currency_scope",),
        )
    valid_count, unavailable_count, pending_count, market_value, unrealized_pnl, reasons = (
        _evaluate_positions(selected)
    )
    status: Literal["valid", "unavailable"] = (
        "valid" if valid_count == len(selected) else "unavailable"
    )
    if status != "valid":
        market_value = None
        unrealized_pnl = None
    return PortfolioCurrencyValuationSummary(
        valuation_run_uid=run.valuation_run_uid,
        source_broker=run.source_broker,
        connection_uid=run.connection_uid,
        source_account_id=run.source_account_id,
        currency=currency,
        evaluated_at_utc=run.evaluated_at.isoformat(),
        included_count=len(selected),
        valid_count=valid_count,
        unavailable_count=unavailable_count,
        reconciliation_pending_count=pending_count,
        status=status,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        reason_codes=reasons,
    )
