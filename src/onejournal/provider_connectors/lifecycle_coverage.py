"""Pure cross-window lifecycle assembly and current-position coverage.

This module has no provider, credential, filesystem, database, or process
capability.  It combines already verified, in-memory lifecycle evidence and
keeps unresolved execution, accounting, and lifecycle evidence fail-closed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Literal, Mapping, Sequence

from onejournal.instruments import InstrumentIdentity, InstrumentIdentityError
from onejournal.provider_connectors.external_acquisition import (
    ConvertedExternalLifecycleEvidence,
    ExternalLifecycleReconciliation,
    lifecycle_fill_reconciliation_key,
    reconcile_lifecycle_rows,
)


LIFECYCLE_COVERAGE_CONTRACT_VERSION = (
    "onejournal.current-position-lifecycle-coverage.v1"
)


class LifecycleCoverageError(ValueError):
    """Raised when lifecycle windows or position targets are ambiguous."""


def _finite(value: Decimal, field: str, *, nonzero: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LifecycleCoverageError(f"{field} must be a finite Decimal")
    if nonzero and value == 0:
        raise LifecycleCoverageError(f"{field} must be non-zero")
    return value


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LifecycleCoverageError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleCoverageError(f"{field} must be a UTC instant")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleCoverageError(f"{field} must be a UTC instant") from exc
    return _utc(parsed, field)


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleCoverageError(f"{field} must be an exact decimal string")
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise LifecycleCoverageError(f"{field} is not decimal-safe") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise LifecycleCoverageError(f"{field} is invalid")
    return parsed


def _canonical_row(row: Mapping[str, str]) -> bytes:
    return json.dumps(
        dict(row), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _freeze(row: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(row))


def _deduplicate(
    rows: Sequence[Mapping[str, str]],
    *,
    identity_field: str,
    label: str,
) -> tuple[tuple[Mapping[str, str], ...], int]:
    seen: dict[str, bytes] = {}
    accepted: list[Mapping[str, str]] = []
    duplicates = 0
    for index, row in enumerate(rows):
        identity = row.get(identity_field, "").strip()
        if not identity:
            raise LifecycleCoverageError(
                f"{label}[{index}] lacks stable {identity_field}"
            )
        signature = _canonical_row(row)
        prior = seen.get(identity)
        if prior is None:
            seen[identity] = signature
            accepted.append(_freeze(row))
        elif prior == signature:
            duplicates += 1
        else:
            raise LifecycleCoverageError(
                f"{label} stable identity has conflicting normalized evidence"
            )
    return tuple(accepted), duplicates


def _unmatched_rows(
    primary: tuple[Mapping[str, str], ...],
    comparison: tuple[Mapping[str, str], ...],
) -> tuple[Mapping[str, str], ...]:
    available = Counter(
        lifecycle_fill_reconciliation_key(row) for row in comparison
    )
    unmatched: list[Mapping[str, str]] = []
    for row in primary:
        key = lifecycle_fill_reconciliation_key(row)
        if available[key] > 0:
            available[key] -= 1
        else:
            unmatched.append(row)
    return tuple(unmatched)


@dataclass(frozen=True)
class CurrentPositionCoverageTarget:
    """Private provider-symbol target from one complete position snapshot."""

    source_instrument_id: str
    asset_class: Literal["equity", "option"]
    broker_quantity: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_instrument_id, str)
            or not self.source_instrument_id.strip()
            or len(self.source_instrument_id) > 128
        ):
            raise LifecycleCoverageError("source_instrument_id is invalid")
        asset_class = self.asset_class.strip().lower()
        if asset_class not in {"equity", "option"}:
            raise LifecycleCoverageError("target asset_class is unsupported")
        object.__setattr__(self, "asset_class", asset_class)
        _finite(self.broker_quantity, "broker_quantity", nonzero=True)


@dataclass(frozen=True)
class PositionLifecycleCoverage:
    """Per-position result; source identity remains private in memory."""

    source_instrument_id: str
    source_instrument_id_sha256: str
    identity: InstrumentIdentity | None
    broker_quantity: Decimal
    transaction_net_quantity: Decimal
    transaction_fill_count: int
    transaction_only_count: int
    order_only_count: int
    lifecycle_leg_count: int
    status: Literal[
        "fill_flat_start_proven", "history_extension_required", "review_required"
    ]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class AssembledLifecycleCoverage:
    """Deterministic, unpersisted result across contiguous verified windows."""

    contract_version: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    window_start_date: date
    window_end_date: date
    evaluated_at: datetime
    external_manifest_sha256s: tuple[str, ...]
    order_rows: tuple[Mapping[str, str], ...]
    transaction_rows: tuple[Mapping[str, str], ...]
    lifecycle_events: tuple[Mapping[str, str], ...]
    lifecycle_event_legs: tuple[Mapping[str, str], ...]
    excluded_post_evaluation_order_rows: int
    excluded_post_evaluation_transaction_rows: int
    excluded_post_evaluation_lifecycle_events: int
    deduplicated_order_rows: int
    deduplicated_transaction_rows: int
    deduplicated_lifecycle_events: int
    deduplicated_lifecycle_event_legs: int
    reconciliation: ExternalLifecycleReconciliation
    only_order_rows: tuple[Mapping[str, str], ...]
    only_transaction_rows: tuple[Mapping[str, str], ...]
    positions: tuple[PositionLifecycleCoverage, ...]
    assembly_sha256: str

    def privacy_safe_audit(self) -> dict[str, object]:
        statuses = Counter(item.status for item in self.positions)
        reasons = Counter(
            reason for item in self.positions for reason in item.reason_codes
        )
        return {
            "schema": "onejournal.current-position-lifecycle-coverage-audit.v1",
            "contract_version": self.contract_version,
            "assembly_sha256": self.assembly_sha256,
            "source_broker": self.source_broker,
            "connection_uid": self.connection_uid,
            "window_start_date": self.window_start_date.isoformat(),
            "window_end_date": self.window_end_date.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "window_count": len(self.external_manifest_sha256s),
            "order_fill_rows": len(self.order_rows),
            "transaction_fill_rows": len(self.transaction_rows),
            "matched_fill_rows": self.reconciliation.matched_rows,
            "only_order_fill_rows": self.reconciliation.only_order_rows,
            "only_transaction_fill_rows": self.reconciliation.only_transaction_rows,
            "position_count": len(self.positions),
            "position_status_counts": dict(sorted(statuses.items())),
            "position_reason_counts": dict(sorted(reasons.items())),
            "excluded_post_evaluation_rows": (
                self.excluded_post_evaluation_order_rows
                + self.excluded_post_evaluation_transaction_rows
                + self.excluded_post_evaluation_lifecycle_events
            ),
            "deduplicated_rows": (
                self.deduplicated_order_rows
                + self.deduplicated_transaction_rows
                + self.deduplicated_lifecycle_events
                + self.deduplicated_lifecycle_event_legs
            ),
            "raw_instrument_identifiers_emitted": False,
            "financial_acceptance": False,
            "final_status": "coverage_assessed_unmaterialized",
        }


def _provider_instrument_id(row: Mapping[str, str]) -> str:
    asset_class = row.get("asset_class", "").strip().lower()
    value = (
        row.get("option_symbol", "")
        if asset_class == "option"
        else row.get("symbol", "")
    )
    return "".join(value.upper().split())


def _target_id(target: CurrentPositionCoverageTarget) -> str:
    return "".join(target.source_instrument_id.upper().split())


def _identity_from_transaction_row(
    row: Mapping[str, str],
) -> InstrumentIdentity:
    asset_class = row.get("asset_class", "").strip().lower()
    try:
        if asset_class in {"stock", "equity"}:
            return InstrumentIdentity(
                asset_class="equity",
                market_scope="US",
                currency=row.get("currency", ""),
                symbol=row.get("symbol", ""),
            )
        if asset_class == "option":
            return InstrumentIdentity(
                asset_class="option",
                market_scope="US",
                currency=row.get("currency", ""),
                underlying_symbol=row.get("underlying_symbol", ""),
                expiry=date.fromisoformat(row.get("expiry", "")),
                option_right=row.get("option_type", "").upper(),
                strike=_decimal(row.get("strike"), "option strike", positive=True),
                multiplier=_decimal(
                    row.get("multiplier"), "option multiplier", positive=True
                ),
            )
    except (InstrumentIdentityError, ValueError) as exc:
        raise LifecycleCoverageError(
            "transaction row lacks a canonical instrument identity"
        ) from exc
    raise LifecycleCoverageError("transaction row asset_class is unsupported")


def _event_leg_provider_id(row: Mapping[str, str]) -> str:
    value = row.get("option_symbol", "") or row.get("symbol", "")
    return "".join(value.upper().split())


def _position_coverage(
    target: CurrentPositionCoverageTarget,
    *,
    transaction_rows: tuple[Mapping[str, str], ...],
    only_order_rows: tuple[Mapping[str, str], ...],
    only_transaction_rows: tuple[Mapping[str, str], ...],
    lifecycle_event_legs: tuple[Mapping[str, str], ...],
    unscoped_lifecycle_review_required: bool,
) -> PositionLifecycleCoverage:
    provider_id = _target_id(target)
    target_transactions = tuple(
        row for row in transaction_rows if _provider_instrument_id(row) == provider_id
    )
    target_transaction_only = tuple(
        row
        for row in only_transaction_rows
        if _provider_instrument_id(row) == provider_id
    )
    target_order_only = tuple(
        row for row in only_order_rows if _provider_instrument_id(row) == provider_id
    )
    target_lifecycle_legs = tuple(
        row
        for row in lifecycle_event_legs
        if _event_leg_provider_id(row) == provider_id
    )

    identities = {_identity_from_transaction_row(row) for row in target_transactions}
    if len(identities) > 1:
        raise LifecycleCoverageError(
            "one provider instrument maps to conflicting canonical identities"
        )
    identity = next(iter(identities), None)
    if identity is not None and identity.asset_class != target.asset_class:
        raise LifecycleCoverageError("target and transaction asset classes differ")

    net_quantity = Decimal("0")
    for row in target_transactions:
        side = row.get("side", "").strip().lower()
        if side not in {"buy", "sell"}:
            raise LifecycleCoverageError("transaction side is unsupported")
        quantity = _decimal(
            row.get("quantity"), "transaction quantity", positive=True
        )
        net_quantity += quantity if side == "buy" else -quantity
    reasons: set[str] = set()
    for row in target_transaction_only:
        reasons.add(
            "transaction_order_id_missing"
            if not row.get("source_order_id", "").strip()
            else "transaction_order_evidence_missing"
        )
    if target_order_only:
        reasons.add("transaction_accounting_evidence_missing")
    if target_lifecycle_legs:
        reasons.add("lifecycle_review_required")
    if unscoped_lifecycle_review_required:
        reasons.add("unscoped_lifecycle_review_required")

    if not target_transactions:
        reasons.add("no_transaction_fill_coverage")
    elif net_quantity != target.broker_quantity:
        reasons.add("transaction_net_differs_from_broker_quantity")

    review_reasons = {
        "transaction_order_id_missing",
        "transaction_order_evidence_missing",
        "transaction_accounting_evidence_missing",
        "lifecycle_review_required",
        "unscoped_lifecycle_review_required",
    }
    if reasons & review_reasons:
        status = "review_required"
    elif reasons:
        status = "history_extension_required"
    else:
        status = "fill_flat_start_proven"

    return PositionLifecycleCoverage(
        source_instrument_id=target.source_instrument_id,
        source_instrument_id_sha256=sha256(
            target.source_instrument_id.encode("utf-8")
        ).hexdigest(),
        identity=identity,
        broker_quantity=target.broker_quantity,
        transaction_net_quantity=net_quantity,
        transaction_fill_count=len(target_transactions),
        transaction_only_count=len(target_transaction_only),
        order_only_count=len(target_order_only),
        lifecycle_leg_count=len(target_lifecycle_legs),
        status=status,
        reason_codes=tuple(sorted(reasons)),
    )


def assemble_current_position_lifecycle_coverage(
    windows: Sequence[ConvertedExternalLifecycleEvidence],
    targets: Sequence[CurrentPositionCoverageTarget],
    *,
    evaluated_at: datetime,
) -> AssembledLifecycleCoverage:
    """Assemble contiguous verified windows and assess current positions."""

    if not windows:
        raise LifecycleCoverageError("at least one lifecycle window is required")
    if not targets:
        raise LifecycleCoverageError("at least one current position is required")
    cutoff = _utc(evaluated_at, "evaluated_at")
    ordered = tuple(sorted(windows, key=lambda item: item.window_start_date))
    scopes = {
        (item.source_broker, item.connection_uid, item.source_account_id)
        for item in ordered
    }
    if len(scopes) != 1:
        raise LifecycleCoverageError("lifecycle windows must share one account scope")
    for prior, current in zip(ordered, ordered[1:]):
        if current.window_start_date != prior.window_end_date + timedelta(days=1):
            raise LifecycleCoverageError(
                "lifecycle windows must be contiguous and non-overlapping"
            )
    if not (
        ordered[0].window_start_date <= cutoff.date() <= ordered[-1].window_end_date
    ):
        raise LifecycleCoverageError(
            "evaluation date must be inside the assembled window coverage"
        )
    target_ids = [_target_id(target) for target in targets]
    if len(set(target_ids)) != len(target_ids):
        raise LifecycleCoverageError("current position targets must be unique")

    raw_orders = [row for window in ordered for row in window.order_rows]
    raw_transactions = [row for window in ordered for row in window.transaction_rows]
    raw_events = [row for window in ordered for row in window.lifecycle_events]
    raw_legs = [row for window in ordered for row in window.lifecycle_event_legs]

    included_orders = []
    excluded_orders = 0
    for row in raw_orders:
        if _instant(row.get("filled_at"), "order filled_at") <= cutoff:
            included_orders.append(row)
        else:
            excluded_orders += 1
    included_transactions = []
    excluded_transactions = 0
    for row in raw_transactions:
        if _instant(row.get("filled_at"), "transaction filled_at") <= cutoff:
            included_transactions.append(row)
        else:
            excluded_transactions += 1
    included_events = []
    excluded_event_uids: set[str] = set()
    for row in raw_events:
        if _instant(row.get("event_at"), "lifecycle event_at") <= cutoff:
            included_events.append(row)
        else:
            excluded_event_uids.add(row.get("event_uid", ""))
    included_legs = [
        row for row in raw_legs if row.get("event_uid", "") not in excluded_event_uids
    ]

    order_rows, duplicate_orders = _deduplicate(
        included_orders, identity_field="source_fill_id", label="order rows"
    )
    transaction_rows, duplicate_transactions = _deduplicate(
        included_transactions,
        identity_field="source_fill_id",
        label="transaction rows",
    )
    lifecycle_events, duplicate_events = _deduplicate(
        included_events, identity_field="event_uid", label="lifecycle events"
    )
    lifecycle_event_legs, duplicate_legs = _deduplicate(
        included_legs,
        identity_field="event_leg_uid",
        label="lifecycle event legs",
    )
    reconciliation = reconcile_lifecycle_rows(order_rows, transaction_rows)
    only_orders = _unmatched_rows(order_rows, transaction_rows)
    only_transactions = _unmatched_rows(transaction_rows, order_rows)
    unscoped_lifecycle_review_required = any(
        row.get("evidence_status", "").strip().lower() != "observed"
        and not _event_leg_provider_id(row)
        for row in lifecycle_event_legs
    )
    position_results = tuple(
        sorted(
            (
                _position_coverage(
                    target,
                    transaction_rows=transaction_rows,
                    only_order_rows=only_orders,
                    only_transaction_rows=only_transactions,
                    lifecycle_event_legs=lifecycle_event_legs,
                    unscoped_lifecycle_review_required=(
                        unscoped_lifecycle_review_required
                    ),
                )
                for target in targets
            ),
            key=lambda item: item.source_instrument_id_sha256,
        )
    )
    source_broker, connection_uid, source_account_id = next(iter(scopes))
    fingerprint_document = {
        "contract_version": LIFECYCLE_COVERAGE_CONTRACT_VERSION,
        "source_broker": source_broker,
        "connection_uid": connection_uid,
        "source_account_id": source_account_id,
        "window_start_date": ordered[0].window_start_date.isoformat(),
        "window_end_date": ordered[-1].window_end_date.isoformat(),
        "evaluated_at": cutoff.isoformat(),
        "external_manifest_sha256s": [
            item.external_manifest_sha256 for item in ordered
        ],
        "order_rows": [sha256(_canonical_row(row)).hexdigest() for row in order_rows],
        "transaction_rows": [
            sha256(_canonical_row(row)).hexdigest() for row in transaction_rows
        ],
        "lifecycle_events": [
            sha256(_canonical_row(row)).hexdigest() for row in lifecycle_events
        ],
        "lifecycle_event_legs": [
            sha256(_canonical_row(row)).hexdigest()
            for row in lifecycle_event_legs
        ],
        "positions": [
            {
                "source_instrument_id_sha256": item.source_instrument_id_sha256,
                "broker_quantity": format(item.broker_quantity, "f"),
                "transaction_net_quantity": format(
                    item.transaction_net_quantity, "f"
                ),
                "status": item.status,
                "reason_codes": list(item.reason_codes),
            }
            for item in position_results
        ],
    }
    assembly_sha256 = sha256(
        json.dumps(
            fingerprint_document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return AssembledLifecycleCoverage(
        contract_version=LIFECYCLE_COVERAGE_CONTRACT_VERSION,
        source_broker=source_broker,
        connection_uid=connection_uid,
        source_account_id=source_account_id,
        window_start_date=ordered[0].window_start_date,
        window_end_date=ordered[-1].window_end_date,
        evaluated_at=cutoff,
        external_manifest_sha256s=tuple(
            item.external_manifest_sha256 for item in ordered
        ),
        order_rows=order_rows,
        transaction_rows=transaction_rows,
        lifecycle_events=lifecycle_events,
        lifecycle_event_legs=lifecycle_event_legs,
        excluded_post_evaluation_order_rows=excluded_orders,
        excluded_post_evaluation_transaction_rows=excluded_transactions,
        excluded_post_evaluation_lifecycle_events=len(excluded_event_uids),
        deduplicated_order_rows=duplicate_orders,
        deduplicated_transaction_rows=duplicate_transactions,
        deduplicated_lifecycle_events=duplicate_events,
        deduplicated_lifecycle_event_legs=duplicate_legs,
        reconciliation=reconciliation,
        only_order_rows=only_orders,
        only_transaction_rows=only_transactions,
        positions=position_results,
        assembly_sha256=assembly_sha256,
    )
