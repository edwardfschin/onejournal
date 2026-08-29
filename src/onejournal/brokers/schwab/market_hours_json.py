"""Lossless, credential-free parsing for Schwab market-hours JSON.

The Schwab response is provider evidence, not a ready-made OneJournal session
authority.  In particular, the observed closed-market sentinel does not name
the reason for closure, and offset-aware timestamps do not identify an IANA
timezone.  This adapter preserves those limitations instead of inferring
holiday, unscheduled-closure, MIC, or timezone facts.

This module has no network, credential, persistence, account, or order
capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any, Literal, Mapping


ADAPTER_VERSION = "schwab-market-hours-json-v1"

_MARKET_TYPE = {
    "equity": "EQUITY",
    "option": "OPTION",
}
_OPEN_PRODUCTS = {
    "equity": ("EQ",),
    "option": ("EQO", "IND"),
}
_SESSION_NAMES = {
    "preMarket": "pre_market",
    "regularMarket": "regular",
    "postMarket": "after_hours",
}
_PRODUCT_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")


class SchwabMarketHoursAdapterError(ValueError):
    """Raised when Schwab market-hours evidence is incomplete or ambiguous."""


@dataclass(frozen=True)
class SchwabMarketHoursPhase:
    """One exact offset-aware provider session interval."""

    market_session: Literal["pre_market", "regular", "after_hours"]
    provider_session_name: str
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class SchwabMarketHoursProduct:
    """One product schedule or the exact provider closed-market sentinel."""

    provider_market: Literal["equity", "option"]
    market_type: str
    market_date: date
    product_code: str
    product_name: str | None
    is_open: bool
    is_closed_sentinel: bool
    phases: tuple[SchwabMarketHoursPhase, ...]


@dataclass(frozen=True)
class SchwabMarketHoursResponse:
    """Validated provider response without invented calendar semantics."""

    market_date: date
    products: tuple[SchwabMarketHoursProduct, ...]
    adapter_version: str = ADAPTER_VERSION

    def product(
        self,
        *,
        provider_market: Literal["equity", "option"],
        product_code: str,
    ) -> SchwabMarketHoursProduct:
        """Select an exact open product or its market-level closed sentinel."""

        matches = [
            product
            for product in self.products
            if product.provider_market == provider_market
            and (
                product.product_code == product_code
                or product.is_closed_sentinel
            )
        ]
        if len(matches) != 1:
            raise SchwabMarketHoursAdapterError(
                "Schwab market-hours product scope is missing or ambiguous"
            )
        return matches[0]


def load_market_hours_json(path: Path) -> dict[str, Any]:
    """Load an already captured Schwab market-hours file."""

    return load_market_hours_json_bytes(path.read_bytes())


def load_market_hours_json_bytes(body: bytes) -> dict[str, Any]:
    """Load finite JSON from immutable captured bytes."""

    if not isinstance(body, bytes) or not body:
        raise SchwabMarketHoursAdapterError(
            "Schwab market-hours response body must be non-empty bytes"
        )
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                SchwabMarketHoursAdapterError(
                    f"invalid non-finite JSON number: {value}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabMarketHoursAdapterError(
            "Schwab market-hours JSON is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise SchwabMarketHoursAdapterError(
            "Schwab market-hours JSON must be a top-level object"
        )
    return payload


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise SchwabMarketHoursAdapterError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SchwabMarketHoursAdapterError(
            f"{field_name} must be YYYY-MM-DD"
        ) from exc


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise SchwabMarketHoursAdapterError(
            f"{field_name} must be an offset-aware timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SchwabMarketHoursAdapterError(
            f"{field_name} must be an offset-aware timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchwabMarketHoursAdapterError(
            f"{field_name} must include an explicit UTC offset"
        )
    return parsed


def _closed_sentinel(
    market_name: str,
    product_map: Mapping[str, Any],
    *,
    expected_date: date,
) -> SchwabMarketHoursProduct | None:
    if set(product_map) != {market_name}:
        return None
    item = product_map[market_name]
    if not isinstance(item, Mapping) or set(item) != {
        "date",
        "marketType",
        "product",
        "isOpen",
    }:
        raise SchwabMarketHoursAdapterError(
            f"{market_name} closed-market sentinel fields do not match contract"
        )
    if (
        _parse_date(item["date"], f"{market_name}.date") != expected_date
        or item["marketType"] != _MARKET_TYPE[market_name]
        or item["product"] != market_name
        or item["isOpen"] is not False
    ):
        raise SchwabMarketHoursAdapterError(
            f"{market_name} closed-market sentinel identity is invalid"
        )
    return SchwabMarketHoursProduct(
        provider_market=market_name,
        market_type=_MARKET_TYPE[market_name],
        market_date=expected_date,
        product_code=market_name,
        product_name=None,
        is_open=False,
        is_closed_sentinel=True,
        phases=(),
    )


def _open_product(
    market_name: str,
    product_code: str,
    item: Any,
    *,
    expected_date: date,
) -> SchwabMarketHoursProduct:
    if not isinstance(item, Mapping) or set(item) != {
        "date",
        "marketType",
        "product",
        "productName",
        "isOpen",
        "sessionHours",
    }:
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code} fields do not match contract"
        )
    if not _PRODUCT_CODE_RE.fullmatch(product_code):
        raise SchwabMarketHoursAdapterError("invalid Schwab product code")
    if (
        _parse_date(item["date"], f"{market_name}.{product_code}.date")
        != expected_date
        or item["marketType"] != _MARKET_TYPE[market_name]
        or item["product"] != product_code
        or item["isOpen"] is not True
    ):
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code} identity or open state is invalid"
        )
    product_name = item["productName"]
    if (
        not isinstance(product_name, str)
        or not product_name.strip()
        or product_name != product_name.strip()
        or len(product_name) > 128
        or any(ord(character) < 32 for character in product_name)
    ):
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code}.productName must be bounded text"
        )
    session_hours = item["sessionHours"]
    if not isinstance(session_hours, Mapping) or not session_hours:
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code}.sessionHours must be non-empty"
        )
    if not set(session_hours).issubset(_SESSION_NAMES):
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code} contains an unsupported session phase"
        )
    if "regularMarket" not in session_hours:
        raise SchwabMarketHoursAdapterError(
            f"{market_name}.{product_code} is missing regularMarket"
        )

    phases: list[SchwabMarketHoursPhase] = []
    for provider_session_name, intervals in session_hours.items():
        if not isinstance(intervals, list) or not intervals:
            raise SchwabMarketHoursAdapterError(
                f"{market_name}.{product_code}.{provider_session_name} "
                "must be a non-empty array"
            )
        for index, interval in enumerate(intervals):
            if not isinstance(interval, Mapping) or set(interval) != {"start", "end"}:
                raise SchwabMarketHoursAdapterError(
                    f"{market_name}.{product_code}.{provider_session_name}[{index}] "
                    "fields do not match contract"
                )
            started_at = _parse_timestamp(
                interval["start"],
                f"{market_name}.{product_code}.{provider_session_name}[{index}].start",
            )
            ended_at = _parse_timestamp(
                interval["end"],
                f"{market_name}.{product_code}.{provider_session_name}[{index}].end",
            )
            if (
                started_at >= ended_at
                or started_at.date() != expected_date
                or ended_at.date() != expected_date
            ):
                raise SchwabMarketHoursAdapterError(
                    f"{market_name}.{product_code}.{provider_session_name}[{index}] "
                    "must be an increasing interval on the requested date"
                )
            phases.append(
                SchwabMarketHoursPhase(
                    market_session=_SESSION_NAMES[provider_session_name],
                    provider_session_name=provider_session_name,
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )

    phases.sort(key=lambda phase: phase.started_at)
    for previous, current in zip(phases, phases[1:]):
        if previous.ended_at > current.started_at:
            raise SchwabMarketHoursAdapterError(
                f"{market_name}.{product_code} session intervals overlap"
            )

    return SchwabMarketHoursProduct(
        provider_market=market_name,
        market_type=_MARKET_TYPE[market_name],
        market_date=expected_date,
        product_code=product_code,
        product_name=product_name,
        is_open=True,
        is_closed_sentinel=False,
        phases=tuple(phases),
    )


def market_hours_from_payload(
    payload: Mapping[str, Any],
    *,
    expected_date: date,
) -> SchwabMarketHoursResponse:
    """Validate the bounded equity/option Schwab market-hours response.

    Open days retain exact provider products and offset-aware phase intervals.
    Closed days retain the observed market-level sentinel.  The result does not
    classify a closed day as a holiday or unscheduled closure and does not turn
    a numeric UTC offset into an IANA timezone.
    """

    if not isinstance(payload, Mapping) or set(payload) != set(_MARKET_TYPE):
        raise SchwabMarketHoursAdapterError(
            "Schwab market-hours scope must contain exactly equity and option"
        )

    products: list[SchwabMarketHoursProduct] = []
    for market_name in ("equity", "option"):
        product_map = payload[market_name]
        if not isinstance(product_map, Mapping) or not product_map:
            raise SchwabMarketHoursAdapterError(
                f"{market_name} product map must be non-empty"
            )
        sentinel = _closed_sentinel(
            market_name,
            product_map,
            expected_date=expected_date,
        )
        if sentinel is not None:
            products.append(sentinel)
            continue

        if set(product_map) != set(_OPEN_PRODUCTS[market_name]):
            raise SchwabMarketHoursAdapterError(
                f"{market_name} open product scope does not match contract"
            )
        for product_code in _OPEN_PRODUCTS[market_name]:
            products.append(
                _open_product(
                    market_name,
                    product_code,
                    product_map[product_code],
                    expected_date=expected_date,
                )
            )

    all_closed = all(product.is_closed_sentinel for product in products)
    any_closed = any(product.is_closed_sentinel for product in products)
    if any_closed and not all_closed:
        raise SchwabMarketHoursAdapterError(
            "mixed open and closed market-level scope is unsupported"
        )
    return SchwabMarketHoursResponse(
        market_date=expected_date,
        products=tuple(products),
    )
