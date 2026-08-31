"""PNL-03 selection of authoritative marks from PNL-02 quote assessments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.market_data import FreshnessAssessment, validate_normalized_quote


@dataclass(frozen=True)
class ValuationMarkAssessment:
    identity: InstrumentIdentity
    quote_uid: str
    evaluated_at: datetime
    status: Literal["valid", "unavailable"]
    freshness_status: str
    freshness_age_seconds: Decimal | None
    quote_market_session: str
    evaluation_market_session: str
    session_authority_uid: str | None
    selected_field: Literal["bid", "ask", "last"] | None
    price: Decimal | None
    policy_version: str
    reason: str | None


def select_valuation_mark(
    *,
    identity: InstrumentIdentity,
    direction: Literal["LONG", "SHORT"],
    quote: NormalizedQuote,
    freshness: FreshnessAssessment,
    expected_provider: str,
    expected_connection_uid: str,
    expected_evaluated_at: datetime | None = None,
) -> ValuationMarkAssessment:
    """Select liquidation-side active marks or eligible closed-session last."""
    def unavailable(reason: str) -> ValuationMarkAssessment:
        return ValuationMarkAssessment(
            identity=identity, quote_uid=quote.quote_uid,
            evaluated_at=freshness.evaluated_at, status="unavailable",
            freshness_status=freshness.status,
            freshness_age_seconds=freshness.age_seconds,
            quote_market_session=freshness.quote_market_session,
            evaluation_market_session=freshness.evaluation_market_session,
            session_authority_uid=freshness.session_authority_uid,
            selected_field=None, price=None, policy_version="pnl-03-mark.v1",
            reason=reason,
        )

    validate_normalized_quote(quote)
    if direction not in {"LONG", "SHORT"}:
        return unavailable("position direction must be LONG or SHORT")
    if (
        freshness.quote_uid != quote.quote_uid
        or freshness.provider != quote.provider
        or freshness.connection_uid != quote.connection_uid
        or freshness.instrument_key != quote.instrument_key
    ):
        return unavailable("freshness assessment is not bound to the supplied quote")
    if quote.provider != expected_provider or quote.connection_uid != expected_connection_uid:
        return unavailable("quote provider or connection does not match position scope")
    if quote.instrument_key != identity.key:
        return unavailable("quote instrument identity is not the canonical PNL-03 identity")
    if quote.currency != identity.currency:
        return unavailable("quote currency does not match instrument identity")
    if expected_evaluated_at is not None and freshness.evaluated_at != expected_evaluated_at:
        return unavailable("freshness evaluation instant does not match valuation scope")
    if not freshness.valuation_allowed:
        return unavailable(f"quote freshness is not valuation-eligible: {freshness.status}")
    if freshness.status == "live_fresh":
        field, price = ("bid", quote.bid) if direction == "LONG" else ("ask", quote.ask)
    elif freshness.status == "market_closed_last":
        field, price = "last", quote.last
    else:
        return unavailable(f"freshness status is not an approved mark source: {freshness.status}")
    if price is None:
        return unavailable(f"required {field} price is absent")
    return ValuationMarkAssessment(
        identity=identity, quote_uid=quote.quote_uid,
        evaluated_at=freshness.evaluated_at, status="valid",
        freshness_status=freshness.status,
        freshness_age_seconds=freshness.age_seconds,
        quote_market_session=freshness.quote_market_session,
        evaluation_market_session=freshness.evaluation_market_session,
        session_authority_uid=freshness.session_authority_uid,
        selected_field=field, price=price, policy_version="pnl-03-mark.v1",
        reason=None,
    )
