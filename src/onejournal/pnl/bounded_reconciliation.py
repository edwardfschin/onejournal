"""Pure bounded PNL-03 FIFO and broker-reconciliation gate.

This boundary consumes already validated, in-memory evidence.  It has no
filesystem, provider, credential, database, process, valuation-mark, or
presentation capability.  Private evidence remains private; the public audit
contains only digests, counts, status, and contract versions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Literal, Mapping, Sequence

from onejournal.brokers.normalized import NormalizedFill
from onejournal.brokers.schwab.position_binding import (
    SchwabPositionPrivateBinding,
    SchwabPositionPrivateBindingError,
    load_schwab_position_private_binding_bytes,
    schwab_position_private_binding_sha256,
)
from onejournal.brokers.schwab.transactions_json import NORMALIZED_FILL_COLUMNS
from onejournal.instruments import InstrumentIdentity, InstrumentIdentityError
from onejournal.pnl.calculations import (
    LotAllocationError,
    build_fill_input_fingerprint,
    build_instrument_key,
    calculate_fifo_pnl_with_lifecycle_events,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
    CanonicalPositionQuantity,
    PositionReconciliationError,
    reconcile_account_positions,
)
from onejournal.provider_connectors.lifecycle_coverage import (
    AssembledLifecycleCoverage,
    LIFECYCLE_COVERAGE_CONTRACT_VERSION,
    PositionLifecycleCoverage,
    calculate_lifecycle_coverage_sha256,
)


BOUNDED_PNL03_FIFO_RECONCILIATION_CONTRACT_VERSION = (
    "onejournal.bounded-pnl03-fifo-reconciliation.v1"
)
INITIAL_BOUNDED_PNL03_ROUTE_VERSION = "pnl-03s-initial-2026-08-31"
INITIAL_BOUNDED_PNL03_ASSEMBLY_SHA256 = (
    "7454c4543439dd6fc49d3e2089ed326ebe6eac0a3cdf8a32a82765d19c041fe6"
)

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_TEXT_RE = re.compile(r"[^\x00-\x1f\x7f]{1,512}")


class BoundedPnl03ReconciliationError(ValueError):
    """Raised when bounded-route evidence is incomplete or mismatched."""


def _safe_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_TEXT_RE.fullmatch(value.strip()):
        raise BoundedPnl03ReconciliationError(f"{field} is required and invalid")
    return value.strip()


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise BoundedPnl03ReconciliationError(
            f"{field} must be a lowercase SHA-256"
        )
    return value


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BoundedPnl03ReconciliationError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BoundedPnl03ReconciliationError(f"{field} must be a UTC instant")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise BoundedPnl03ReconciliationError(
            f"{field} must be an ISO-8601 instant"
        ) from exc
    return _utc(parsed, field)


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise BoundedPnl03ReconciliationError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise BoundedPnl03ReconciliationError(
            f"{field} must be an ISO date"
        ) from exc


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise BoundedPnl03ReconciliationError(
            f"{field} must be an exact decimal string"
        )
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise BoundedPnl03ReconciliationError(f"{field} is invalid") from exc
    if not parsed.is_finite():
        raise BoundedPnl03ReconciliationError(f"{field} must be finite")
    return parsed


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value in {None, ""}:
        return None
    return _decimal(value, field)


def _provider_key(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise BoundedPnl03ReconciliationError(f"{field} is invalid")
    return "".join(value.upper().split())


def _asset_class(value: object, field: str) -> Literal["equity", "option"]:
    if not isinstance(value, str):
        raise BoundedPnl03ReconciliationError(f"{field} is invalid")
    normalized = value.strip().lower()
    if normalized in {"stock", "equity"}:
        return "equity"
    if normalized == "option":
        return "option"
    raise BoundedPnl03ReconciliationError(f"{field} is unsupported")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalized_fill_from_lifecycle_transaction_row(
    row: Mapping[str, str],
    *,
    fetched_at: datetime,
    raw_path: str,
) -> NormalizedFill:
    """Convert one exact accepted transaction row with explicit private lineage."""

    if set(row) != set(NORMALIZED_FILL_COLUMNS):
        raise BoundedPnl03ReconciliationError(
            "lifecycle transaction row fields do not match the normalized contract"
        )
    checked_fetched_at = _utc(fetched_at, "fetched_at")
    checked_raw_path = _safe_text(raw_path, "raw_path")
    source_broker = _safe_text(row.get("source_broker"), "source_broker")
    source_account_id = _safe_text(
        row.get("source_account_id"), "source_account_id"
    )
    source_fill_id = _safe_text(row.get("source_fill_id"), "source_fill_id")
    asset_class = _asset_class(row.get("asset_class"), "asset_class")
    expiry = (
        _date(row.get("expiry"), "expiry")
        if str(row.get("expiry", "")).strip()
        else None
    )
    return NormalizedFill(
        fill_uid=f"{source_broker}:{source_account_id}:{source_fill_id}",
        source_broker=source_broker,
        source_account_id=source_account_id,
        source_fill_id=source_fill_id,
        source_order_id=_optional_text(row.get("source_order_id")),
        episode_group_id=_optional_text(row.get("episode_group_id")),
        asof=_date(row.get("asof"), "asof"),
        filled_at=_instant(row.get("filled_at"), "filled_at"),
        asset_class="option" if asset_class == "option" else "stock",
        symbol=_safe_text(row.get("symbol"), "symbol").upper(),
        side=_safe_text(row.get("side"), "side").upper(),
        quantity=_decimal(row.get("quantity"), "quantity"),
        fill_price=_decimal(row.get("fill_price"), "fill_price"),
        commission=_decimal(row.get("commission"), "commission"),
        fees=_decimal(row.get("fees"), "fees"),
        currency=_safe_text(row.get("currency"), "currency").upper(),
        fetched_at=checked_fetched_at,
        raw_path=checked_raw_path,
        option_symbol=_optional_text(row.get("option_symbol")),
        underlying_symbol=_optional_text(row.get("underlying_symbol")),
        option_type=_optional_text(row.get("option_type")),
        expiry=expiry,
        strike=_optional_decimal(row.get("strike"), "strike"),
        multiplier=_optional_decimal(row.get("multiplier"), "multiplier"),
        open_close=_optional_text(row.get("open_close")),
        execution_venue=_optional_text(row.get("execution_venue")),
        liquidity_flag=_optional_text(row.get("liquidity_flag")),
    )


@dataclass(frozen=True)
class BoundedPnl03RouteSpec:
    """Explicit approved evidence identity and expected coverage counts."""

    route_version: str
    expected_binding_sha256: str
    expected_snapshot_uid: str
    expected_assembly_sha256: str
    expected_fill_fingerprint: str
    expected_position_count: int
    expected_eligible_count: int
    expected_history_extension_count: int
    expected_review_required_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "route_version", _safe_text(self.route_version, "route_version")
        )
        _digest(self.expected_binding_sha256, "expected_binding_sha256")
        object.__setattr__(
            self,
            "expected_snapshot_uid",
            _safe_text(self.expected_snapshot_uid, "expected_snapshot_uid"),
        )
        _digest(self.expected_assembly_sha256, "expected_assembly_sha256")
        _digest(self.expected_fill_fingerprint, "expected_fill_fingerprint")
        counts = (
            self.expected_position_count,
            self.expected_eligible_count,
            self.expected_history_extension_count,
            self.expected_review_required_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise BoundedPnl03ReconciliationError(
                "bounded-route position counts must be non-negative integers"
            )
        if self.expected_position_count <= 0 or self.expected_eligible_count <= 0:
            raise BoundedPnl03ReconciliationError(
                "bounded route requires positions and an eligible scope"
            )
        if self.expected_position_count != sum(counts[1:]):
            raise BoundedPnl03ReconciliationError(
                "bounded-route status counts must reconcile to the complete snapshot"
            )
        if self.route_version == INITIAL_BOUNDED_PNL03_ROUTE_VERSION and (
            self.expected_assembly_sha256 != INITIAL_BOUNDED_PNL03_ASSEMBLY_SHA256
            or counts != (53, 46, 4, 3)
        ):
            raise BoundedPnl03ReconciliationError(
                "initial PNL-03 route must preserve the frozen 46/4/3 baseline"
            )


def initial_bounded_pnl03_route_spec(
    *,
    expected_binding_sha256: str,
    expected_snapshot_uid: str,
    expected_fill_fingerprint: str,
) -> BoundedPnl03RouteSpec:
    """Build the accepted ADR-0022 initial route without weakening its counts."""

    return BoundedPnl03RouteSpec(
        route_version=INITIAL_BOUNDED_PNL03_ROUTE_VERSION,
        expected_binding_sha256=expected_binding_sha256,
        expected_snapshot_uid=expected_snapshot_uid,
        expected_assembly_sha256=INITIAL_BOUNDED_PNL03_ASSEMBLY_SHA256,
        expected_fill_fingerprint=expected_fill_fingerprint,
        expected_position_count=53,
        expected_eligible_count=46,
        expected_history_extension_count=4,
        expected_review_required_count=3,
    )


@dataclass(frozen=True)
class BoundedPnl03PositionResult:
    """One complete-snapshot member after the FIFO/reconciliation gate."""

    identity: InstrumentIdentity
    coverage_status: str
    coverage_reason_codes: tuple[str, ...]
    broker_quantity: Decimal
    canonical_quantity: Decimal | None
    open_cost_basis: Decimal | None
    reconciliation_status: str
    status: Literal["fifo_reconciled", "reconciliation_pending", "unavailable"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BoundedPnl03FifoReconciliationRun:
    """Deterministic result over the complete snapshot and bounded eligible scope."""

    contract_version: str
    route_version: str
    run_uid: str
    binding_sha256: str
    snapshot_uid: str
    assembly_sha256: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    evaluated_at: datetime
    calculation_version: str
    fill_fingerprint: str
    complete_position_count: int
    eligible_count: int
    fifo_reconciled_count: int
    reconciliation_pending_count: int
    unavailable_count: int
    positions: tuple[BoundedPnl03PositionResult, ...]
    eligible_cost_basis_subtotal_by_currency: Mapping[str, Decimal] | None
    portfolio_cost_basis_by_currency: None
    subtotal_status: Literal["eligible_subtotal"]
    complete_portfolio_totals_available: Literal[False]
    financial_acceptance: Literal[False]
    final_status: Literal["eligible_fifo_reconciled", "reconciliation_pending"]

    def privacy_safe_audit(self) -> dict[str, object]:
        """Return no provider symbol, identity, quantity, cost, path, or account."""

        return {
            "schema": "onejournal.bounded-pnl03-fifo-reconciliation-audit.v1",
            "contract_version": self.contract_version,
            "route_version": self.route_version,
            "run_uid": self.run_uid,
            "binding_sha256": self.binding_sha256,
            "snapshot_uid": self.snapshot_uid,
            "assembly_sha256": self.assembly_sha256,
            "fill_fingerprint": self.fill_fingerprint,
            "calculation_version": self.calculation_version,
            "complete_position_count": self.complete_position_count,
            "eligible_count": self.eligible_count,
            "fifo_reconciled_count": self.fifo_reconciled_count,
            "reconciliation_pending_count": self.reconciliation_pending_count,
            "unavailable_count": self.unavailable_count,
            "eligible_cost_basis_subtotal_available": (
                self.eligible_cost_basis_subtotal_by_currency is not None
            ),
            "subtotal_status": self.subtotal_status,
            "complete_portfolio_totals_available": False,
            "raw_instrument_identifiers_emitted": False,
            "financial_values_emitted": False,
            "financial_acceptance": False,
            "final_status": self.final_status,
        }


def _validate_scope(
    *,
    spec: BoundedPnl03RouteSpec,
    binding: SchwabPositionPrivateBinding,
    binding_sha256: str,
    coverage: AssembledLifecycleCoverage,
    broker_snapshot: BrokerPositionSnapshot,
) -> tuple[
    dict[str, InstrumentIdentity],
    dict[str, PositionLifecycleCoverage],
    dict[InstrumentIdentity, BrokerPositionRecord],
]:
    if binding_sha256 != spec.expected_binding_sha256:
        raise BoundedPnl03ReconciliationError(
            "private binding digest does not match the approved route"
        )
    if coverage.contract_version != LIFECYCLE_COVERAGE_CONTRACT_VERSION:
        raise BoundedPnl03ReconciliationError(
            "lifecycle coverage contract version is unsupported"
        )
    if coverage.assembly_sha256 != spec.expected_assembly_sha256:
        raise BoundedPnl03ReconciliationError(
            "lifecycle assembly does not match the approved route"
        )
    if calculate_lifecycle_coverage_sha256(coverage) != coverage.assembly_sha256:
        raise BoundedPnl03ReconciliationError(
            "lifecycle assembly content does not match its digest"
        )
    if broker_snapshot.snapshot_uid != spec.expected_snapshot_uid:
        raise BoundedPnl03ReconciliationError(
            "broker snapshot does not match the approved route"
        )
    if coverage.source_broker != "schwab" or broker_snapshot.source_broker != "schwab":
        raise BoundedPnl03ReconciliationError(
            "Schwab private binding requires Schwab evidence"
        )
    scopes = {
        (binding.connection_uid, binding.source_account_id),
        (coverage.connection_uid, coverage.source_account_id),
        (broker_snapshot.connection_uid, broker_snapshot.source_account_id),
    }
    if len(scopes) != 1:
        raise BoundedPnl03ReconciliationError(
            "binding, lifecycle, and snapshot account scopes differ"
        )
    if coverage.evaluated_at != broker_snapshot.retrieved_at:
        raise BoundedPnl03ReconciliationError(
            "lifecycle cutoff must equal the broker snapshot retrieval instant"
        )
    if not broker_snapshot.account_complete:
        raise BoundedPnl03ReconciliationError(
            "bounded route requires a complete broker account snapshot"
        )
    if len(coverage.positions) != spec.expected_position_count:
        raise BoundedPnl03ReconciliationError(
            "coverage position count does not match the approved route"
        )
    if len(broker_snapshot.positions) != spec.expected_position_count:
        raise BoundedPnl03ReconciliationError(
            "broker snapshot count does not match the approved route"
        )
    if len(binding.mappings) != spec.expected_position_count:
        raise BoundedPnl03ReconciliationError(
            "private binding count does not match the complete snapshot"
        )
    status_counts = Counter(item.status for item in coverage.positions)
    expected_status_counts = {
        "fill_flat_start_proven": spec.expected_eligible_count,
        "history_extension_required": spec.expected_history_extension_count,
        "review_required": spec.expected_review_required_count,
    }
    if dict(status_counts) != {
        key: value for key, value in expected_status_counts.items() if value
    }:
        raise BoundedPnl03ReconciliationError(
            "coverage status counts do not match the approved route"
        )

    mapping_by_provider: dict[str, InstrumentIdentity] = {}
    for mapping in binding.mappings:
        key = _provider_key(mapping.provider_symbol, "binding provider symbol")
        if key in mapping_by_provider:
            raise BoundedPnl03ReconciliationError(
                "private binding contains a normalized provider-symbol collision"
            )
        mapping_by_provider[key] = mapping.identity
    coverage_by_provider: dict[str, PositionLifecycleCoverage] = {}
    for position in coverage.positions:
        key = _provider_key(
            position.source_instrument_id, "coverage source instrument"
        )
        if key in coverage_by_provider:
            raise BoundedPnl03ReconciliationError(
                "coverage contains a normalized provider-symbol collision"
            )
        expected_source_digest = sha256(
            position.source_instrument_id.encode("utf-8")
        ).hexdigest()
        if position.source_instrument_id_sha256 != expected_source_digest:
            raise BoundedPnl03ReconciliationError(
                "coverage source instrument digest is inconsistent"
            )
        coverage_by_provider[key] = position
    if set(mapping_by_provider) != set(coverage_by_provider):
        raise BoundedPnl03ReconciliationError(
            "private binding does not exactly cover lifecycle positions"
        )
    snapshot_by_identity = {
        position.identity: position for position in broker_snapshot.positions
    }
    if set(mapping_by_provider.values()) != set(snapshot_by_identity):
        raise BoundedPnl03ReconciliationError(
            "private binding does not exactly cover broker snapshot identities"
        )
    for provider_key, coverage_position in coverage_by_provider.items():
        identity = mapping_by_provider[provider_key]
        if (
            coverage_position.identity is not None
            and coverage_position.identity != identity
        ):
            raise BoundedPnl03ReconciliationError(
                "lifecycle identity conflicts with the private binding"
            )
        broker_position = snapshot_by_identity[identity]
        if broker_position.quantity != coverage_position.broker_quantity:
            raise BoundedPnl03ReconciliationError(
                "lifecycle and broker snapshot quantities differ"
            )
        if (
            coverage_position.status == "fill_flat_start_proven"
            and coverage_position.identity is None
        ):
            raise BoundedPnl03ReconciliationError(
                "eligible coverage lacks transaction-authoritative identity"
            )
    return mapping_by_provider, coverage_by_provider, snapshot_by_identity


def _validate_fill_against_row(
    fill: NormalizedFill,
    row: Mapping[str, str],
    *,
    expected_identity: InstrumentIdentity,
    evaluated_at: datetime,
) -> None:
    source_broker = _safe_text(row.get("source_broker"), "transaction source_broker")
    source_account_id = _safe_text(
        row.get("source_account_id"), "transaction source_account_id"
    )
    source_fill_id = _safe_text(
        row.get("source_fill_id"), "transaction source_fill_id"
    )
    source_order_id = _safe_text(
        row.get("source_order_id"), "transaction source_order_id"
    )
    expected_fill_uid = f"{source_broker}:{source_account_id}:{source_fill_id}"
    if (
        fill.fill_uid != expected_fill_uid
        or fill.source_broker != source_broker
        or fill.source_account_id != source_account_id
        or fill.source_fill_id != source_fill_id
        or fill.source_order_id != source_order_id
    ):
        raise BoundedPnl03ReconciliationError(
            "normalized fill source identity differs from transaction evidence"
        )
    filled_at = _instant(row.get("filled_at"), "transaction filled_at")
    if _utc(fill.filled_at, "fill filled_at") != filled_at:
        raise BoundedPnl03ReconciliationError(
            "normalized fill instant differs from transaction evidence"
        )
    if filled_at > evaluated_at:
        raise BoundedPnl03ReconciliationError(
            "normalized fill occurs after the bounded evaluation instant"
        )
    if fill.asof != _date(row.get("asof"), "transaction asof"):
        raise BoundedPnl03ReconciliationError(
            "normalized fill asof differs from transaction evidence"
        )
    if _asset_class(fill.asset_class, "fill asset_class") != _asset_class(
        row.get("asset_class"), "transaction asset_class"
    ):
        raise BoundedPnl03ReconciliationError(
            "normalized fill asset class differs from transaction evidence"
        )
    if fill.symbol.strip().upper() != str(row.get("symbol", "")).strip().upper():
        raise BoundedPnl03ReconciliationError(
            "normalized fill symbol differs from transaction evidence"
        )
    if fill.side.strip().lower() != str(row.get("side", "")).strip().lower():
        raise BoundedPnl03ReconciliationError(
            "normalized fill side differs from transaction evidence"
        )
    for field, actual in (
        ("quantity", fill.quantity),
        ("fill_price", fill.fill_price),
        ("commission", fill.commission),
        ("fees", fill.fees),
    ):
        if actual != _decimal(row.get(field), f"transaction {field}"):
            raise BoundedPnl03ReconciliationError(
                f"normalized fill {field} differs from transaction evidence"
            )
    if fill.currency.strip().upper() != str(row.get("currency", "")).strip().upper():
        raise BoundedPnl03ReconciliationError(
            "normalized fill currency differs from transaction evidence"
        )
    optional_strings = (
        ("option_symbol", fill.option_symbol),
        ("underlying_symbol", fill.underlying_symbol),
        ("option_type", fill.option_type),
        ("open_close", fill.open_close),
        ("execution_venue", fill.execution_venue),
        ("liquidity_flag", fill.liquidity_flag),
        ("episode_group_id", fill.episode_group_id),
    )
    for field, actual in optional_strings:
        expected = str(row.get(field, "")).strip()
        if (actual or "").strip() != expected:
            raise BoundedPnl03ReconciliationError(
                f"normalized fill {field} differs from transaction evidence"
            )
    expected_expiry = (
        _date(row.get("expiry"), "transaction expiry")
        if row.get("expiry", "").strip()
        else None
    )
    if fill.expiry != expected_expiry:
        raise BoundedPnl03ReconciliationError(
            "normalized fill expiry differs from transaction evidence"
        )
    for field, actual in (("strike", fill.strike), ("multiplier", fill.multiplier)):
        if actual != _optional_decimal(row.get(field), f"transaction {field}"):
            raise BoundedPnl03ReconciliationError(
                f"normalized fill {field} differs from transaction evidence"
            )
    if fill.fetched_at.tzinfo is None or fill.fetched_at.utcoffset() is None:
        raise BoundedPnl03ReconciliationError("fill fetched_at must include a timezone")
    _safe_text(fill.raw_path, "fill raw_path")
    try:
        identity = InstrumentIdentity.from_fill(fill)
    except InstrumentIdentityError as exc:
        raise BoundedPnl03ReconciliationError(
            "normalized fill lacks canonical identity"
        ) from exc
    if identity != expected_identity:
        raise BoundedPnl03ReconciliationError(
            "normalized fill identity conflicts with the private binding"
        )


def run_bounded_pnl03_fifo_reconciliation(
    *,
    spec: BoundedPnl03RouteSpec,
    private_binding_bytes: bytes,
    coverage: AssembledLifecycleCoverage,
    broker_snapshot: BrokerPositionSnapshot,
    eligible_transaction_fills: Sequence[NormalizedFill],
    max_snapshot_age_seconds: int,
) -> BoundedPnl03FifoReconciliationRun:
    """Run FIFO/reconciliation only for the exact bounded eligible positions."""

    try:
        binding = load_schwab_position_private_binding_bytes(private_binding_bytes)
        binding_sha256 = schwab_position_private_binding_sha256(
            private_binding_bytes
        )
    except SchwabPositionPrivateBindingError as exc:
        raise BoundedPnl03ReconciliationError(
            "private binding bytes failed the canonical contract"
        ) from exc
    mapping_by_provider, coverage_by_provider, _snapshot_by_identity = _validate_scope(
        spec=spec,
        binding=binding,
        binding_sha256=binding_sha256,
        coverage=coverage,
        broker_snapshot=broker_snapshot,
    )
    evaluated_at = _utc(coverage.evaluated_at, "coverage evaluated_at")
    eligible_provider_keys = {
        provider_key
        for provider_key, position in coverage_by_provider.items()
        if position.status == "fill_flat_start_proven"
    }
    expected_rows: dict[str, Mapping[str, str]] = {}
    for row in coverage.transaction_rows:
        provider_key = _provider_key(
            row.get("option_symbol")
            if str(row.get("asset_class", "")).strip().lower() == "option"
            else row.get("symbol"),
            "transaction provider instrument",
        )
        if provider_key not in eligible_provider_keys:
            continue
        source_fill_id = _safe_text(
            row.get("source_fill_id"), "transaction source_fill_id"
        )
        if source_fill_id in expected_rows:
            raise BoundedPnl03ReconciliationError(
                "eligible transaction rows contain duplicate source fill identity"
            )
        expected_rows[source_fill_id] = row
    supplied_by_source_fill: dict[str, NormalizedFill] = {}
    for fill in eligible_transaction_fills:
        if fill.source_fill_id in supplied_by_source_fill:
            raise BoundedPnl03ReconciliationError(
                "eligible normalized fills contain duplicate source identity"
            )
        supplied_by_source_fill[fill.source_fill_id] = fill
    if set(supplied_by_source_fill) != set(expected_rows):
        raise BoundedPnl03ReconciliationError(
            "normalized fill scope does not exactly match eligible transaction evidence"
        )
    checked_fills: list[NormalizedFill] = []
    for source_fill_id in sorted(expected_rows):
        row = expected_rows[source_fill_id]
        provider_key = _provider_key(
            row.get("option_symbol")
            if str(row.get("asset_class", "")).strip().lower() == "option"
            else row.get("symbol"),
            "transaction provider instrument",
        )
        fill = supplied_by_source_fill[source_fill_id]
        _validate_fill_against_row(
            fill,
            row,
            expected_identity=mapping_by_provider[provider_key],
            evaluated_at=evaluated_at,
        )
        checked_fills.append(fill)
    if not checked_fills:
        raise BoundedPnl03ReconciliationError(
            "eligible route requires transaction-authoritative normalized fills"
        )

    fill_fingerprint = build_fill_input_fingerprint(tuple(checked_fills))
    if fill_fingerprint != spec.expected_fill_fingerprint:
        raise BoundedPnl03ReconciliationError(
            "eligible fill fingerprint does not match the approved route"
        )
    try:
        fifo = calculate_fifo_pnl_with_lifecycle_events(tuple(checked_fills), ())
    except LotAllocationError as exc:
        raise BoundedPnl03ReconciliationError(
            "eligible transaction fills failed FIFO allocation"
        ) from exc
    identity_by_legacy: dict[str, InstrumentIdentity] = {}
    for fill in checked_fills:
        identity = InstrumentIdentity.from_fill(fill)
        legacy = build_instrument_key(fill)
        prior = identity_by_legacy.get(legacy)
        if prior is not None and prior != identity:
            raise BoundedPnl03ReconciliationError(
                "legacy FIFO key maps to conflicting canonical identities"
            )
        identity_by_legacy[legacy] = identity
    canonical_positions: list[CanonicalPositionQuantity] = []
    cost_basis_by_identity: dict[InstrumentIdentity, Decimal] = {}
    for scope, group in fifo.groups.items():
        if group.open_quantity == 0:
            continue
        source_broker, source_account_id, legacy, _currency = scope
        identity = identity_by_legacy.get(legacy)
        if identity is None:
            raise BoundedPnl03ReconciliationError(
                "open FIFO group lacks canonical private binding"
            )
        if identity in cost_basis_by_identity:
            raise BoundedPnl03ReconciliationError(
                "multiple FIFO groups map to one canonical identity"
            )
        cost_basis_by_identity[identity] = group.open_cost_basis
        canonical_positions.append(
            CanonicalPositionQuantity(
                source_broker=source_broker,
                connection_uid=coverage.connection_uid,
                source_account_id=source_account_id,
                identity=identity,
                quantity=group.open_quantity,
                asof=broker_snapshot.asof,
                evaluated_at=evaluated_at,
                calculation_version=fifo.calculation_version,
                open_cost_basis=group.open_cost_basis,
                legacy_instrument_key=legacy,
            )
        )
    try:
        reconciliations = {
            item.identity: item
            for item in reconcile_account_positions(
                tuple(canonical_positions),
                broker_snapshot,
                evaluated_at=evaluated_at,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
            )
        }
    except PositionReconciliationError as exc:
        raise BoundedPnl03ReconciliationError(
            "eligible FIFO positions failed reconciliation scope validation"
        ) from exc

    position_results: list[BoundedPnl03PositionResult] = []
    eligible_costs: dict[str, Decimal] = {}
    fifo_reconciled_count = 0
    reconciliation_pending_count = 0
    unavailable_count = 0
    for provider_key, coverage_position in coverage_by_provider.items():
        identity = mapping_by_provider[provider_key]
        reconciliation = reconciliations[identity]
        if coverage_position.status != "fill_flat_start_proven":
            unavailable_count += 1
            status: Literal[
                "fifo_reconciled", "reconciliation_pending", "unavailable"
            ] = "unavailable"
            reasons = tuple(
                sorted(
                    set(coverage_position.reason_codes)
                    | {f"coverage_{coverage_position.status}"}
                )
            )
            canonical_quantity = None
            open_cost_basis = None
        elif reconciliation.status != "valid":
            reconciliation_pending_count += 1
            status = "reconciliation_pending"
            reasons = ("eligible_fifo_reconciliation_pending",)
            canonical_quantity = reconciliation.canonical_quantity
            open_cost_basis = None
        else:
            fifo_reconciled_count += 1
            status = "fifo_reconciled"
            reasons = ()
            canonical_quantity = reconciliation.canonical_quantity
            open_cost_basis = cost_basis_by_identity[identity]
            eligible_costs[identity.currency] = (
                eligible_costs.get(identity.currency, Decimal("0"))
                + open_cost_basis
            )
        position_results.append(
            BoundedPnl03PositionResult(
                identity=identity,
                coverage_status=coverage_position.status,
                coverage_reason_codes=coverage_position.reason_codes,
                broker_quantity=coverage_position.broker_quantity,
                canonical_quantity=canonical_quantity,
                open_cost_basis=open_cost_basis,
                reconciliation_status=reconciliation.status,
                status=status,
                reason_codes=reasons,
            )
        )
    ordered_positions = tuple(
        sorted(position_results, key=lambda item: item.identity.key)
    )
    eligible_count = len(eligible_provider_keys)
    all_eligible_reconciled = fifo_reconciled_count == eligible_count
    eligible_subtotal = dict(sorted(eligible_costs.items())) if all_eligible_reconciled else None
    run_document = {
        "contract_version": BOUNDED_PNL03_FIFO_RECONCILIATION_CONTRACT_VERSION,
        "route_version": spec.route_version,
        "binding_sha256": binding_sha256,
        "snapshot_uid": broker_snapshot.snapshot_uid,
        "assembly_sha256": coverage.assembly_sha256,
        "fill_fingerprint": fill_fingerprint,
        "calculation_version": fifo.calculation_version,
        "positions": [
            {
                "identity": item.identity.key,
                "coverage_status": item.coverage_status,
                "broker_quantity": format(item.broker_quantity, "f"),
                "canonical_quantity": (
                    format(item.canonical_quantity, "f")
                    if item.canonical_quantity is not None
                    else None
                ),
                "status": item.status,
                "reason_codes": list(item.reason_codes),
            }
            for item in ordered_positions
        ],
    }
    run_digest = sha256(
        json.dumps(run_document, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return BoundedPnl03FifoReconciliationRun(
        contract_version=BOUNDED_PNL03_FIFO_RECONCILIATION_CONTRACT_VERSION,
        route_version=spec.route_version,
        run_uid=f"bounded-pnl03-fifo-reconciliation:{run_digest}",
        binding_sha256=binding_sha256,
        snapshot_uid=broker_snapshot.snapshot_uid,
        assembly_sha256=coverage.assembly_sha256,
        source_broker=broker_snapshot.source_broker,
        connection_uid=broker_snapshot.connection_uid,
        source_account_id=broker_snapshot.source_account_id,
        asof=broker_snapshot.asof,
        evaluated_at=evaluated_at,
        calculation_version=fifo.calculation_version,
        fill_fingerprint=fill_fingerprint,
        complete_position_count=len(ordered_positions),
        eligible_count=eligible_count,
        fifo_reconciled_count=fifo_reconciled_count,
        reconciliation_pending_count=reconciliation_pending_count,
        unavailable_count=unavailable_count,
        positions=ordered_positions,
        eligible_cost_basis_subtotal_by_currency=eligible_subtotal,
        portfolio_cost_basis_by_currency=None,
        subtotal_status="eligible_subtotal",
        complete_portfolio_totals_available=False,
        financial_acceptance=False,
        final_status=(
            "eligible_fifo_reconciled"
            if all_eligible_reconciled
            else "reconciliation_pending"
        ),
    )
