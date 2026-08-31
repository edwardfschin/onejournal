"""Versioned broker-independent instrument identity for PNL-03.

This module intentionally has no provider, persistence, quote, or calculation
capability.  It defines typed identity only; provider symbols remain mappings
outside this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Literal


INSTRUMENT_IDENTITY_VERSION = "onejournal.instrument-identity.v1"
_SYMBOL_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,31}")


class InstrumentIdentityError(ValueError):
    """Raised when a canonical instrument cannot be identified exactly."""


def _decimal_text(value: Decimal, field_name: str) -> str:
    if not value.is_finite() or value <= 0:
        raise InstrumentIdentityError(f"{field_name} must be a positive finite decimal")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


@dataclass(frozen=True)
class InstrumentIdentity:
    """A typed canonical identity for supported Phase 1 US instruments."""

    asset_class: Literal["equity", "option"]
    market_scope: str
    currency: str
    symbol: str | None = None
    underlying_symbol: str | None = None
    expiry: date | None = None
    option_right: Literal["CALL", "PUT"] | None = None
    strike: Decimal | None = None
    multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        asset_class = self.asset_class.strip().lower()
        market_scope = self.market_scope.strip().upper()
        currency = self.currency.strip().upper()
        symbol = self.symbol.strip().upper() if self.symbol else None
        underlying = self.underlying_symbol.strip().upper() if self.underlying_symbol else None
        right = self.option_right.strip().upper() if self.option_right else None
        if asset_class not in {"equity", "option"}:
            raise InstrumentIdentityError("asset_class must be equity or option")
        if market_scope != "US":
            raise InstrumentIdentityError("initial identity scope supports US instruments only")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise InstrumentIdentityError("currency must be an explicit three-letter code")
        if asset_class == "equity":
            if not symbol or not _SYMBOL_RE.fullmatch(symbol):
                raise InstrumentIdentityError("equity symbol is required and invalid")
            if any(value is not None for value in (underlying, self.expiry, right, self.strike, self.multiplier)):
                raise InstrumentIdentityError("equity identity must not include option fields")
        else:
            if not underlying or not _SYMBOL_RE.fullmatch(underlying):
                raise InstrumentIdentityError("option underlying_symbol is required and invalid")
            if self.expiry is None:
                raise InstrumentIdentityError("option expiry is required")
            if right not in {"CALL", "PUT"}:
                raise InstrumentIdentityError("option_right must be CALL or PUT")
            if self.strike is None or self.multiplier is None:
                raise InstrumentIdentityError("option strike and multiplier are required")
            _decimal_text(self.strike, "strike")
            _decimal_text(self.multiplier, "multiplier")
            if symbol is not None:
                raise InstrumentIdentityError("option identity must use underlying_symbol, not symbol")
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "market_scope", market_scope)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "underlying_symbol", underlying)
        object.__setattr__(self, "option_right", right)

    @property
    def key(self) -> str:
        """Return the deterministic v1 serialization used across PNL-03."""
        if self.asset_class == "equity":
            return f"instrument.v1|equity|{self.market_scope}|{self.currency}|{self.symbol}"
        return (
            f"instrument.v1|option|{self.market_scope}|{self.currency}|"
            f"{self.underlying_symbol}|{self.expiry.isoformat()}|{self.option_right}|"
            f"{_decimal_text(self.strike, 'strike')}|{_decimal_text(self.multiplier, 'multiplier')}"
        )

    @classmethod
    def from_fill(cls, fill) -> "InstrumentIdentity":
        """Build identity from an already-normalized supported fill."""
        asset_class = str(fill.asset_class).strip().lower()
        if asset_class in {"stock", "equity"}:
            return cls(asset_class="equity", market_scope="US", currency=fill.currency, symbol=fill.symbol)
        if asset_class == "option":
            return cls(
                asset_class="option",
                market_scope="US",
                currency=fill.currency,
                underlying_symbol=fill.underlying_symbol,
                expiry=fill.expiry,
                option_right=fill.option_type,
                strike=fill.strike,
                multiplier=fill.multiplier,
            )
        raise InstrumentIdentityError(f"unsupported fill asset_class: {fill.asset_class}")
