"""Pure fail-closed valuation gate for the bounded eligible PNL-03 scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Literal, Mapping

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.market_data import FreshnessAssessment
from onejournal.pnl.bounded_reconciliation import BoundedPnl03FifoReconciliationRun
from onejournal.pnl.valuation_marks import ValuationMarkAssessment, select_valuation_mark


BOUNDED_PNL03_VALUATION_CONTRACT_VERSION = "onejournal.bounded-pnl03-valuation.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class BoundedPnl03ValuationError(ValueError):
    """Raised when valuation evidence does not match the approved bounded scope."""


@dataclass(frozen=True)
class BoundedPnl03ValuedPosition:
    """One complete-snapshot member after bounded mark selection."""

    identity: InstrumentIdentity
    coverage_status: str
    broker_quantity: Decimal
    reconciliation_status: str
    canonical_quantity: Decimal | None
    open_cost_basis: Decimal | None
    mark: ValuationMarkAssessment | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    status: Literal["valued", "mark_unavailable", "unavailable"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BoundedPnl03ValuationRun:
    """Private valuation result whose ordinary audit emits no financial values."""

    contract_version: str
    route_version: str
    run_uid: str
    reconciliation_run_uid: str
    binding_sha256: str
    snapshot_uid: str
    assembly_sha256: str
    quote_evidence_sha256: str
    quote_scope_sha256: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    evaluated_at: datetime
    calculation_version: str
    fill_fingerprint: str
    max_reconciliation_age_seconds: int
    reconciliation_age_seconds: Decimal
    complete_position_count: int
    eligible_count: int
    valid_mark_count: int
    mark_unavailable_count: int
    unavailable_count: int
    positions: tuple[BoundedPnl03ValuedPosition, ...]
    eligible_cost_basis_subtotal_by_currency: Mapping[str, Decimal]
    eligible_market_value_subtotal_by_currency: Mapping[str, Decimal] | None
    eligible_unrealized_pnl_subtotal_by_currency: Mapping[str, Decimal] | None
    portfolio_market_value_by_currency: None
    portfolio_unrealized_pnl_by_currency: None
    subtotal_status: Literal["eligible_subtotal", "unavailable"]
    complete_portfolio_totals_available: Literal[False]
    financial_acceptance: Literal[False]
    final_status: Literal["eligible_valued", "mark_unavailable"]

    def privacy_safe_audit(self) -> dict[str, object]:
        """Return counts and lineage only, never identities, marks, or values."""

        return {
            "schema": "onejournal.bounded-pnl03-valuation-audit.v1",
            "contract_version": self.contract_version,
            "route_version": self.route_version,
            "run_uid": self.run_uid,
            "reconciliation_run_uid": self.reconciliation_run_uid,
            "binding_sha256": self.binding_sha256,
            "snapshot_uid": self.snapshot_uid,
            "assembly_sha256": self.assembly_sha256,
            "quote_evidence_sha256": self.quote_evidence_sha256,
            "quote_scope_sha256": self.quote_scope_sha256,
            "asof": self.asof.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "calculation_version": self.calculation_version,
            "fill_fingerprint": self.fill_fingerprint,
            "max_reconciliation_age_seconds": self.max_reconciliation_age_seconds,
            "reconciliation_age_seconds": format(
                self.reconciliation_age_seconds, "f"
            ),
            "complete_position_count": self.complete_position_count,
            "eligible_count": self.eligible_count,
            "valid_mark_count": self.valid_mark_count,
            "mark_unavailable_count": self.mark_unavailable_count,
            "unavailable_count": self.unavailable_count,
            "eligible_cost_basis_subtotal_available": True,
            "eligible_market_value_subtotal_available": (
                self.eligible_market_value_subtotal_by_currency is not None
            ),
            "eligible_unrealized_pnl_subtotal_available": (
                self.eligible_unrealized_pnl_subtotal_by_currency is not None
            ),
            "subtotal_status": self.subtotal_status,
            "portfolio_total_available": False,
            "complete_portfolio_totals_available": False,
            "private_financial_values_emitted": False,
            "raw_instrument_identifiers_emitted": False,
            "financial_acceptance": False,
            "final_status": self.final_status,
        }


def _digest_document(document: object) -> str:
    return sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def run_bounded_pnl03_valuation(
    *,
    reconciliation: BoundedPnl03FifoReconciliationRun,
    quote_evidence_sha256: str,
    quotes: Mapping[
        InstrumentIdentity,
        tuple[NormalizedQuote, FreshnessAssessment],
    ],
    evaluated_at: datetime,
    max_reconciliation_age_seconds: int,
) -> BoundedPnl03ValuationRun:
    """Select marks and calculate only an approved reconciliation's eligible subtotal."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise BoundedPnl03ValuationError("evaluated_at must include a timezone")
    evaluated = evaluated_at.astimezone(UTC)
    if (
        type(max_reconciliation_age_seconds) is not int
        or max_reconciliation_age_seconds < 0
    ):
        raise BoundedPnl03ValuationError(
            "max_reconciliation_age_seconds must be a non-negative integer"
        )
    reconciliation_evaluated_at = reconciliation.evaluated_at
    if (
        reconciliation_evaluated_at.tzinfo is None
        or reconciliation_evaluated_at.utcoffset() is None
    ):
        raise BoundedPnl03ValuationError(
            "reconciliation evaluated_at must include a timezone"
        )
    reconciliation_age_seconds = Decimal(
        str(
            (
                evaluated
                - reconciliation_evaluated_at.astimezone(UTC)
            ).total_seconds()
        )
    )
    if (
        reconciliation_age_seconds < 0
        or reconciliation_age_seconds > Decimal(max_reconciliation_age_seconds)
    ):
        raise BoundedPnl03ValuationError(
            "reconciliation is outside the approved valuation age limit"
        )
    if not isinstance(quote_evidence_sha256, str) or not _SHA256.fullmatch(
        quote_evidence_sha256
    ):
        raise BoundedPnl03ValuationError(
            "quote_evidence_sha256 must be a lowercase SHA-256 digest"
        )
    if (
        reconciliation.final_status != "eligible_fifo_reconciled"
        or reconciliation.reconciliation_pending_count != 0
        or reconciliation.complete_position_count <= 0
        or reconciliation.eligible_count <= 0
        or reconciliation.fifo_reconciled_count != reconciliation.eligible_count
        or reconciliation.unavailable_count
        != reconciliation.complete_position_count - reconciliation.eligible_count
        or len(reconciliation.positions) != reconciliation.complete_position_count
        or reconciliation.eligible_cost_basis_subtotal_by_currency is None
        or reconciliation.portfolio_cost_basis_by_currency is not None
        or reconciliation.subtotal_status != "eligible_subtotal"
        or reconciliation.complete_portfolio_totals_available is not False
        or reconciliation.financial_acceptance is not False
    ):
        raise BoundedPnl03ValuationError(
            "reconciliation does not preserve its approved bounded route"
        )

    eligible = {
        item.identity: item
        for item in reconciliation.positions
        if item.status == "fifo_reconciled"
    }
    unresolved = {
        item.identity: item
        for item in reconciliation.positions
        if item.status == "unavailable"
    }
    if (
        len(eligible) != reconciliation.eligible_count
        or len(unresolved) != reconciliation.unavailable_count
        or len(eligible) + len(unresolved) != len(reconciliation.positions)
    ):
        raise BoundedPnl03ValuationError(
            "reconciliation position membership does not match its counts"
        )
    unexpected_quotes = set(quotes) - set(eligible)
    if unexpected_quotes:
        raise BoundedPnl03ValuationError(
            "quote scope contains a non-eligible position"
        )

    results: list[BoundedPnl03ValuedPosition] = []
    market_values: dict[str, Decimal] = {}
    unrealized_values: dict[str, Decimal] = {}
    quote_scope_rows: list[dict[str, object]] = []
    valid_mark_count = 0
    mark_unavailable_count = 0

    for identity, position in sorted(eligible.items(), key=lambda item: item[0].key):
        evidence = quotes.get(identity)
        mark: ValuationMarkAssessment | None = None
        market_value: Decimal | None = None
        unrealized_pnl: Decimal | None = None
        reasons: tuple[str, ...]
        if evidence is None:
            status: Literal["valued", "mark_unavailable", "unavailable"] = (
                "mark_unavailable"
            )
            reasons = ("eligible_quote_missing",)
            mark_unavailable_count += 1
        else:
            quote, freshness = evidence
            quantity = position.canonical_quantity
            if quantity is None or quantity == 0 or position.open_cost_basis is None:
                raise BoundedPnl03ValuationError(
                    "eligible reconciliation lacks quantity or cost basis"
                )
            direction: Literal["LONG", "SHORT"] = (
                "LONG" if quantity > 0 else "SHORT"
            )
            mark = select_valuation_mark(
                identity=identity,
                direction=direction,
                quote=quote,
                freshness=freshness,
                expected_provider=reconciliation.source_broker,
                expected_connection_uid=reconciliation.connection_uid,
                expected_evaluated_at=evaluated,
            )
            if mark.status != "valid":
                status = "mark_unavailable"
                reasons = ("eligible_mark_unavailable",)
                mark_unavailable_count += 1
            else:
                if mark.price is None:
                    raise BoundedPnl03ValuationError(
                        "valid valuation mark lacks a price"
                    )
                multiplier = (
                    identity.multiplier
                    if identity.asset_class == "option"
                    else Decimal("1")
                )
                assert multiplier is not None
                market_value = quantity * mark.price * multiplier
                unrealized_pnl = market_value - position.open_cost_basis
                currency = identity.currency
                market_values[currency] = market_values.get(
                    currency, Decimal("0")
                ) + market_value
                unrealized_values[currency] = unrealized_values.get(
                    currency, Decimal("0")
                ) + unrealized_pnl
                status = "valued"
                reasons = ()
                valid_mark_count += 1
        quote_scope_rows.append(
            {
                "identity": identity.key,
                "quote_uid": mark.quote_uid if mark is not None else None,
                "mark_status": mark.status if mark is not None else "missing",
                "selected_field": mark.selected_field if mark is not None else None,
                "selected_price": (
                    format(mark.price, "f")
                    if mark is not None and mark.price is not None
                    else None
                ),
            }
        )
        results.append(
            BoundedPnl03ValuedPosition(
                identity=identity,
                coverage_status=position.coverage_status,
                broker_quantity=position.broker_quantity,
                reconciliation_status=position.reconciliation_status,
                canonical_quantity=position.canonical_quantity,
                open_cost_basis=position.open_cost_basis,
                mark=mark,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                status=status,
                reason_codes=reasons,
            )
        )

    for identity, position in sorted(unresolved.items(), key=lambda item: item[0].key):
        results.append(
            BoundedPnl03ValuedPosition(
                identity=identity,
                coverage_status=position.coverage_status,
                broker_quantity=position.broker_quantity,
                reconciliation_status=position.reconciliation_status,
                canonical_quantity=None,
                open_cost_basis=None,
                mark=None,
                market_value=None,
                unrealized_pnl=None,
                status="unavailable",
                reason_codes=position.reason_codes,
            )
        )

    all_marks_valid = valid_mark_count == len(eligible)
    quote_scope_sha256 = _digest_document(quote_scope_rows)
    run_uid = "bounded-pnl03-valuation:" + _digest_document(
        {
            "contract_version": BOUNDED_PNL03_VALUATION_CONTRACT_VERSION,
            "route_version": reconciliation.route_version,
            "reconciliation_run_uid": reconciliation.run_uid,
            "quote_evidence_sha256": quote_evidence_sha256,
            "quote_scope_sha256": quote_scope_sha256,
            "evaluated_at": evaluated.isoformat(),
            "max_reconciliation_age_seconds": max_reconciliation_age_seconds,
            "reconciliation_age_seconds": format(
                reconciliation_age_seconds, "f"
            ),
        }
    )
    ordered_results = tuple(sorted(results, key=lambda item: item.identity.key))
    return BoundedPnl03ValuationRun(
        contract_version=BOUNDED_PNL03_VALUATION_CONTRACT_VERSION,
        route_version=reconciliation.route_version,
        run_uid=run_uid,
        reconciliation_run_uid=reconciliation.run_uid,
        binding_sha256=reconciliation.binding_sha256,
        snapshot_uid=reconciliation.snapshot_uid,
        assembly_sha256=reconciliation.assembly_sha256,
        quote_evidence_sha256=quote_evidence_sha256,
        quote_scope_sha256=quote_scope_sha256,
        source_broker=reconciliation.source_broker,
        connection_uid=reconciliation.connection_uid,
        source_account_id=reconciliation.source_account_id,
        asof=reconciliation.asof,
        evaluated_at=evaluated,
        calculation_version=reconciliation.calculation_version,
        fill_fingerprint=reconciliation.fill_fingerprint,
        max_reconciliation_age_seconds=max_reconciliation_age_seconds,
        reconciliation_age_seconds=reconciliation_age_seconds,
        complete_position_count=reconciliation.complete_position_count,
        eligible_count=reconciliation.eligible_count,
        valid_mark_count=valid_mark_count,
        mark_unavailable_count=mark_unavailable_count,
        unavailable_count=reconciliation.unavailable_count,
        positions=ordered_results,
        eligible_cost_basis_subtotal_by_currency=dict(
            sorted(reconciliation.eligible_cost_basis_subtotal_by_currency.items())
        ),
        eligible_market_value_subtotal_by_currency=(
            dict(sorted(market_values.items())) if all_marks_valid else None
        ),
        eligible_unrealized_pnl_subtotal_by_currency=(
            dict(sorted(unrealized_values.items())) if all_marks_valid else None
        ),
        portfolio_market_value_by_currency=None,
        portfolio_unrealized_pnl_by_currency=None,
        subtotal_status="eligible_subtotal" if all_marks_valid else "unavailable",
        complete_portfolio_totals_available=False,
        financial_acceptance=False,
        final_status="eligible_valued" if all_marks_valid else "mark_unavailable",
    )
