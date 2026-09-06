"""Versioned Phase 1 Schwab evidence assembly and cross-family validation.

This boundary accepts only already converted, credential-free evidence. It has
no provider, credential, filesystem, database, UI, or order capability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping

from onejournal.market_data.ingestion import validate_quote_capture
from onejournal.market_data.quotes import QuoteFreshnessPolicy
from onejournal.market_data.sessions import (
    ProviderMarketSessionAuthority,
    validate_provider_session_authority_binding,
)
from onejournal.provider_connectors.external_acquisition import (
    ConvertedExternalLifecycleEvidence,
    ConvertedExternalPositionSnapshot,
    ConvertedExternalQuoteCapture,
)


SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION = (
    "onejournal.schwab-phase1-evidence-assembly.v1"
)
SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2 = (
    "onejournal.schwab-phase1-evidence-assembly.v2"
)
SCHWAB_PHASE1_EVIDENCE_ARTIFACT_VERSION = (
    "onejournal.schwab-phase1-evidence-artifact.v1"
)
SCHWAB_PHASE1_EVIDENCE_ARTIFACT_V2 = (
    "onejournal.schwab-phase1-evidence-artifact.v2"
)
FAMILY_ORDER = (
    "account",
    "positions",
    "orders",
    "transactions",
    "fills",
    "cash",
    "quotes",
    "sessions",
)
FAMILY_ORDER_V2 = (
    "account",
    "positions",
    "orders",
    "transactions",
    "lifecycle_events",
    "lifecycle_event_legs",
    "fills",
    "cash",
    "quotes",
    "sessions",
)
FamilyName = Literal[
    "account",
    "positions",
    "orders",
    "transactions",
    "lifecycle_events",
    "lifecycle_event_legs",
    "fills",
    "cash",
    "quotes",
    "sessions",
]
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_MACHINE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,191}")


class SchwabEvidenceAssemblyError(ValueError):
    """Raised when required evidence cannot form one safe account assembly."""


@dataclass(frozen=True)
class SchwabEvidenceFamily:
    family: FamilyName
    source_manifest_sha256s: tuple[str, ...]
    source_raw_sha256s: tuple[str, ...]
    source_record_count: int
    normalized_record_count: int
    excluded_record_count: int
    exclusion_reasons: tuple[str, ...]
    records: tuple[Mapping[str, Any], ...]
    family_fingerprint: str


@dataclass(frozen=True)
class SchwabEvidenceReconciliation:
    matched_fill_rows: int
    order_only_fill_rows: int
    transaction_only_fill_rows: int
    position_count: int
    quote_count: int
    positions_without_quotes: int
    session_count: int
    cash_review_required_rows: int
    all_positions_have_quotes: bool
    all_quotes_have_session_authority: bool


@dataclass(frozen=True)
class SchwabPhase1EvidenceAssembly:
    assembly_uid: str
    contract_version: str
    provider: str
    connection_uid: str
    source_account_id: str
    asof: date
    assembled_at_utc: datetime
    lifecycle_window_start: date
    lifecycle_window_end: date
    families: tuple[SchwabEvidenceFamily, ...]
    reconciliation: SchwabEvidenceReconciliation
    final_status: Literal["ready", "review_required"]
    result_fingerprint: str


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabEvidenceAssemblyError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _machine_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _MACHINE_ID_RE.fullmatch(value):
        raise SchwabEvidenceAssemblyError(
            f"{field_name} must be a secret-safe opaque identifier"
        )
    return value


def _digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise SchwabEvidenceAssemblyError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise SchwabEvidenceAssemblyError("financial values must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc(value, "datetime value").isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise SchwabEvidenceAssemblyError(
        f"unsupported evidence value type: {type(value).__name__}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def canonical_schwab_evidence_json(value: Any) -> str:
    """Return the contract's decimal-safe canonical JSON representation."""

    return _canonical_json(value)


def freeze_schwab_evidence_value(value: Any) -> Any:
    """Recursively freeze a decoded evidence value for immutable read-back."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): freeze_schwab_evidence_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(freeze_schwab_evidence_value(item) for item in value)
    return value


def _family_payload(family: SchwabEvidenceFamily) -> dict[str, Any]:
    return {
        "family": family.family,
        "source_manifest_sha256s": family.source_manifest_sha256s,
        "source_raw_sha256s": family.source_raw_sha256s,
        "source_record_count": family.source_record_count,
        "normalized_record_count": family.normalized_record_count,
        "excluded_record_count": family.excluded_record_count,
        "exclusion_reasons": family.exclusion_reasons,
        "records": family.records,
    }


def _family(
    family: FamilyName,
    *,
    source_manifest_sha256s: tuple[str, ...],
    source_raw_sha256s: tuple[str, ...],
    source_record_count: int,
    records: tuple[Mapping[str, Any], ...],
    excluded_record_count: int = 0,
    exclusion_reasons: tuple[str, ...] = (),
) -> SchwabEvidenceFamily:
    candidate = SchwabEvidenceFamily(
        family=family,
        source_manifest_sha256s=tuple(sorted(set(source_manifest_sha256s))),
        source_raw_sha256s=tuple(sorted(set(source_raw_sha256s))),
        source_record_count=source_record_count,
        normalized_record_count=len(records),
        excluded_record_count=excluded_record_count,
        exclusion_reasons=tuple(sorted(set(exclusion_reasons))),
        records=tuple(
            freeze_schwab_evidence_value(_json_value(record)) for record in records
        ),
        family_fingerprint="pending",
    )
    fingerprint = sha256(_canonical_json(_family_payload(candidate)).encode()).hexdigest()
    result = replace(candidate, family_fingerprint=fingerprint)
    validate_schwab_evidence_family(result)
    return result


def validate_schwab_evidence_family(family: SchwabEvidenceFamily) -> None:
    if family.family not in FAMILY_ORDER_V2:
        raise SchwabEvidenceAssemblyError("unsupported evidence family")
    if family.source_record_count < 0 or family.normalized_record_count < 0:
        raise SchwabEvidenceAssemblyError("family counts must not be negative")
    if family.excluded_record_count < 0:
        raise SchwabEvidenceAssemblyError("excluded_record_count must not be negative")
    if family.normalized_record_count != len(family.records):
        raise SchwabEvidenceAssemblyError("family normalized count is inconsistent")
    if family.source_record_count != (
        family.normalized_record_count + family.excluded_record_count
    ):
        raise SchwabEvidenceAssemblyError(
            "family source count must equal normalized plus excluded records"
        )
    if not family.source_manifest_sha256s or not family.source_raw_sha256s:
        raise SchwabEvidenceAssemblyError("every family requires exact source lineage")
    for index, value in enumerate(family.source_manifest_sha256s):
        _digest(value, f"source_manifest_sha256s[{index}]")
    for index, value in enumerate(family.source_raw_sha256s):
        _digest(value, f"source_raw_sha256s[{index}]")
    if family.excluded_record_count and not family.exclusion_reasons:
        raise SchwabEvidenceAssemblyError(
            "excluded records require explicit privacy-safe reasons"
        )
    expected = sha256(_canonical_json(_family_payload(family)).encode()).hexdigest()
    if family.family_fingerprint != expected:
        raise SchwabEvidenceAssemblyError("family fingerprint does not match content")


def _position_record(record: Any) -> Mapping[str, Any]:
    identity = record.identity
    return {
        "instrument_key": identity.key,
        "identity": asdict(identity),
        "quantity": record.quantity,
        "provider_position_id": record.provider_position_id,
        "broker_average_cost": record.broker_average_cost,
        "broker_tax_lot_average_price": record.broker_tax_lot_average_price,
        "broker_market_value": record.broker_market_value,
        "broker_unrealized_pnl": record.broker_unrealized_pnl,
    }


def _record_id(record: Mapping[str, Any], field: str, family: str) -> str:
    value = str(record.get(field, "")).strip()
    if not value:
        raise SchwabEvidenceAssemblyError(f"{family} record lacks {field}")
    return value


def _ensure_unique(
    records: tuple[Mapping[str, Any], ...], *, field: str, family: str
) -> None:
    values = [_record_id(record, field, family) for record in records]
    if len(set(values)) != len(values):
        raise SchwabEvidenceAssemblyError(f"{family} records contain duplicate {field}")


def _window_observation_record(
    record: Mapping[str, Any],
    *,
    window: ConvertedExternalLifecycleEvidence,
    identity_field: str,
    observation_field: str,
) -> Mapping[str, Any]:
    """Bind a logical Schwab record to its exact source-window observation."""

    _record_id(record, identity_field, "lifecycle")
    payload = {
        **dict(record),
        "source_manifest_sha256": window.external_manifest_sha256,
        "source_window_start_date": window.window_start_date,
        "source_window_end_date": window.window_end_date,
    }
    observation_digest = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return {
        **payload,
        observation_field: f"schwab-evidence-observation:{observation_digest}",
    }


def _assembly_payload(assembly: SchwabPhase1EvidenceAssembly) -> dict[str, Any]:
    return {
        "contract_version": assembly.contract_version,
        "provider": assembly.provider,
        "connection_uid": assembly.connection_uid,
        "source_account_id": assembly.source_account_id,
        "asof": assembly.asof,
        "assembled_at_utc": assembly.assembled_at_utc,
        "lifecycle_window_start": assembly.lifecycle_window_start,
        "lifecycle_window_end": assembly.lifecycle_window_end,
        "families": [
            {**_family_payload(family), "family_fingerprint": family.family_fingerprint}
            for family in assembly.families
        ],
        "reconciliation": asdict(assembly.reconciliation),
        "final_status": assembly.final_status,
    }


def calculate_schwab_evidence_assembly_fingerprint(
    assembly: SchwabPhase1EvidenceAssembly,
) -> str:
    return sha256(_canonical_json(_assembly_payload(assembly)).encode()).hexdigest()


def validate_schwab_phase1_evidence_assembly(
    assembly: SchwabPhase1EvidenceAssembly,
) -> None:
    if assembly.contract_version not in {
        SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
        SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    }:
        raise SchwabEvidenceAssemblyError("unsupported assembly contract version")
    if assembly.provider != "schwab":
        raise SchwabEvidenceAssemblyError("Phase 1 assembly provider must be schwab")
    _machine_id(assembly.connection_uid, "connection_uid")
    _machine_id(assembly.source_account_id, "source_account_id")
    _utc(assembly.assembled_at_utc, "assembled_at_utc")
    if assembly.lifecycle_window_start > assembly.lifecycle_window_end:
        raise SchwabEvidenceAssemblyError("lifecycle window is inverted")
    if assembly.lifecycle_window_end > assembly.asof:
        raise SchwabEvidenceAssemblyError("lifecycle evidence extends beyond asof")
    expected_family_order = (
        FAMILY_ORDER_V2
        if assembly.contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
        else FAMILY_ORDER
    )
    if tuple(family.family for family in assembly.families) != expected_family_order:
        raise SchwabEvidenceAssemblyError("assembly must contain every family once")
    for family in assembly.families:
        validate_schwab_evidence_family(family)
    by_name = {family.family: family for family in assembly.families}
    _ensure_unique(by_name["positions"].records, field="instrument_key", family="positions")
    _ensure_unique(
        by_name["orders"].records,
        field="order_observation_uid",
        family="orders",
    )
    _ensure_unique(
        by_name["transactions"].records,
        field="transaction_observation_uid",
        family="transactions",
    )
    if assembly.contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2:
        _ensure_unique(
            by_name["lifecycle_events"].records,
            field="event_observation_uid",
            family="lifecycle_events",
        )
        _ensure_unique(
            by_name["lifecycle_event_legs"].records,
            field="event_leg_observation_uid",
            family="lifecycle_event_legs",
        )
        event_uids = {
            _record_id(record, "event_uid", "lifecycle_events")
            for record in by_name["lifecycle_events"].records
        }
        leg_event_uids = {
            _record_id(record, "event_uid", "lifecycle_event_legs")
            for record in by_name["lifecycle_event_legs"].records
        }
        if not leg_event_uids.issubset(event_uids):
            raise SchwabEvidenceAssemblyError(
                "lifecycle event legs contain an unknown event"
            )
    _ensure_unique(by_name["fills"].records, field="source_fill_id", family="fills")
    _ensure_unique(
        by_name["cash"].records,
        field="cash_observation_uid",
        family="cash",
    )
    _ensure_unique(by_name["quotes"].records, field="quote_uid", family="quotes")
    _ensure_unique(
        by_name["quotes"].records,
        field="instrument_key",
        family="quotes",
    )
    _ensure_unique(by_name["sessions"].records, field="authority_uid", family="sessions")
    if len(by_name["account"].records) != 1:
        raise SchwabEvidenceAssemblyError("assembly requires one account record")
    account_record = by_name["account"].records[0]
    expected_account_fields = {
        "source_broker": assembly.provider,
        "connection_uid": assembly.connection_uid,
        "source_account_id": assembly.source_account_id,
        "asof": assembly.asof.isoformat(),
    }
    for field_name, expected_value in expected_account_fields.items():
        if account_record.get(field_name) != expected_value:
            raise SchwabEvidenceAssemblyError(
                f"account record {field_name} differs from assembly"
            )
    for family in assembly.families:
        for record in family.records:
            account = record.get("source_account_id")
            if account is not None and account != assembly.source_account_id:
                raise SchwabEvidenceAssemblyError(
                    f"{family.family} record differs from assembly account"
                )
            provider = record.get("source_broker", record.get("provider"))
            if provider is not None and provider != assembly.provider:
                raise SchwabEvidenceAssemblyError(
                    f"{family.family} record differs from assembly provider"
                )
            connection = record.get("connection_uid")
            if connection is not None and connection != assembly.connection_uid:
                raise SchwabEvidenceAssemblyError(
                    f"{family.family} record differs from assembly connection"
                )
    if assembly.reconciliation.position_count != len(by_name["positions"].records):
        raise SchwabEvidenceAssemblyError("position reconciliation count is inconsistent")
    if assembly.reconciliation.quote_count != len(by_name["quotes"].records):
        raise SchwabEvidenceAssemblyError("quote reconciliation count is inconsistent")
    position_keys = {
        _record_id(record, "instrument_key", "positions")
        for record in by_name["positions"].records
    }
    quote_keys = {
        _record_id(record, "instrument_key", "quotes")
        for record in by_name["quotes"].records
    }
    if not quote_keys.issubset(position_keys):
        raise SchwabEvidenceAssemblyError(
            "quote evidence contains a non-position instrument"
        )
    if assembly.reconciliation.positions_without_quotes < 0:
        raise SchwabEvidenceAssemblyError(
            "positions_without_quotes must not be negative"
        )
    if (
        assembly.reconciliation.positions_without_quotes
        != len(position_keys - quote_keys)
    ):
        raise SchwabEvidenceAssemblyError(
            "position/quote coverage counts are inconsistent"
        )
    if assembly.reconciliation.all_positions_have_quotes != (
        assembly.reconciliation.positions_without_quotes == 0
    ):
        raise SchwabEvidenceAssemblyError(
            "all_positions_have_quotes is inconsistent"
        )
    if assembly.reconciliation.session_count != len(by_name["sessions"].records):
        raise SchwabEvidenceAssemblyError("session reconciliation count is inconsistent")
    session_quote_uids = {
        _record_id(record, "quote_uid", "sessions")
        for record in by_name["sessions"].records
    }
    quote_uids = {
        _record_id(record, "quote_uid", "quotes")
        for record in by_name["quotes"].records
    }
    if session_quote_uids != quote_uids:
        raise SchwabEvidenceAssemblyError(
            "session authority must exactly cover quote evidence"
        )
    cash_statuses = [record.get("evidence_status") for record in by_name["cash"].records]
    if any(status not in {"observed", "review_required"} for status in cash_statuses):
        raise SchwabEvidenceAssemblyError("cash evidence status is invalid")
    if assembly.reconciliation.cash_review_required_rows != sum(
        status == "review_required" for status in cash_statuses
    ):
        raise SchwabEvidenceAssemblyError("cash reconciliation count is inconsistent")
    if (
        assembly.reconciliation.matched_fill_rows
        + assembly.reconciliation.transaction_only_fill_rows
        != len(by_name["fills"].records)
    ):
        raise SchwabEvidenceAssemblyError("fill reconciliation count is inconsistent")
    if not assembly.reconciliation.all_quotes_have_session_authority:
        raise SchwabEvidenceAssemblyError("every quote requires session authority")
    expected_status = (
        "ready"
        if assembly.reconciliation.order_only_fill_rows == 0
        and assembly.reconciliation.transaction_only_fill_rows == 0
        and by_name["fills"].excluded_record_count == 0
        and assembly.reconciliation.cash_review_required_rows == 0
        and (
            assembly.contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION
            or (
                by_name["lifecycle_events"].excluded_record_count == 0
                and by_name["lifecycle_event_legs"].excluded_record_count == 0
                and all(
                    record.get("evidence_status") == "observed"
                    for record in by_name["lifecycle_event_legs"].records
                )
            )
        )
        else "review_required"
    )
    if assembly.final_status != expected_status:
        raise SchwabEvidenceAssemblyError("assembly final_status is inconsistent")
    expected_fingerprint = calculate_schwab_evidence_assembly_fingerprint(assembly)
    if assembly.result_fingerprint != expected_fingerprint:
        raise SchwabEvidenceAssemblyError("assembly fingerprint does not match content")
    expected_uid = f"schwab-evidence-assembly:{expected_fingerprint}"
    if assembly.assembly_uid != expected_uid:
        raise SchwabEvidenceAssemblyError("assembly_uid does not match content")


def build_schwab_phase1_evidence_assembly(
    *,
    position: ConvertedExternalPositionSnapshot,
    lifecycle_windows: tuple[ConvertedExternalLifecycleEvidence, ...],
    quote: ConvertedExternalQuoteCapture,
    session_authorities: tuple[ProviderMarketSessionAuthority, ...],
    assembled_at_utc: datetime,
    freshness_policy: QuoteFreshnessPolicy,
    contract_version: str = SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
) -> SchwabPhase1EvidenceAssembly:
    """Assemble all required Phase 1 families from accepted in-memory evidence."""

    if contract_version not in {
        SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
        SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    }:
        raise SchwabEvidenceAssemblyError("unsupported requested assembly version")
    snapshot = position.snapshot
    capture = quote.capture
    assembled_at = _utc(assembled_at_utc, "assembled_at_utc")
    validate_quote_capture(capture, policy=freshness_policy)
    if not snapshot.account_complete:
        raise SchwabEvidenceAssemblyError("complete account position evidence is required")
    if position.account_record is None:
        raise SchwabEvidenceAssemblyError("direct Schwab account evidence is required")
    expected_scope = ("schwab", snapshot.connection_uid, snapshot.source_account_id)
    if (
        snapshot.source_broker,
        snapshot.connection_uid,
        snapshot.source_account_id,
    ) != expected_scope:
        raise SchwabEvidenceAssemblyError("position snapshot scope is invalid")
    if (capture.provider, capture.connection_uid) != expected_scope[:2]:
        raise SchwabEvidenceAssemblyError("quote capture differs from position scope")
    if capture.asof != snapshot.asof:
        raise SchwabEvidenceAssemblyError("position and quote asof must match")
    if assembled_at < max(snapshot.retrieved_at, capture.evaluated_at):
        raise SchwabEvidenceAssemblyError("assembly precedes required current evidence")
    if (
        not position.raw_response_bytes
        or sha256(position.raw_response_bytes).hexdigest() != snapshot.raw_sha256
    ):
        raise SchwabEvidenceAssemblyError("position raw bytes do not match lineage")
    if (
        not quote.raw_response_bytes
        or sha256(quote.raw_response_bytes).hexdigest() != capture.source.raw_sha256
    ):
        raise SchwabEvidenceAssemblyError("quote raw bytes do not match lineage")
    _digest(position.external_manifest_sha256, "position manifest digest")
    _digest(quote.external_manifest_sha256, "quote manifest digest")
    if not lifecycle_windows:
        raise SchwabEvidenceAssemblyError("at least one lifecycle window is required")
    windows = tuple(sorted(lifecycle_windows, key=lambda item: item.window_start_date))
    for index, window in enumerate(windows):
        if (
            window.source_broker,
            window.connection_uid,
            window.source_account_id,
        ) != expected_scope:
            raise SchwabEvidenceAssemblyError("lifecycle window differs from account scope")
        _digest(window.external_manifest_sha256, "lifecycle manifest digest")
        if len(window.raw_response_bytes) != 2 or any(
            not body for body in window.raw_response_bytes.values()
        ):
            raise SchwabEvidenceAssemblyError(
                "lifecycle window requires exact order and transaction bytes"
            )
        if window.window_end_date > snapshot.asof:
            raise SchwabEvidenceAssemblyError("lifecycle window extends beyond snapshot")
        if index and window.window_start_date != (
            windows[index - 1].window_end_date + timedelta(days=1)
        ):
            raise SchwabEvidenceAssemblyError(
                "lifecycle windows must be contiguous and non-overlapping"
            )
        if len(window.order_records) == 0 and window.order_stats.top_level_orders:
            raise SchwabEvidenceAssemblyError("lifecycle window lacks direct order records")
        if len(window.transaction_records) != window.transaction_stats.transactions:
            raise SchwabEvidenceAssemblyError(
                "lifecycle window lacks direct transaction records"
            )

    position_keys = {item.identity.key for item in snapshot.positions}
    quote_by_key = {item.instrument_key: item for item in capture.quotes}
    if not set(quote_by_key).issubset(position_keys):
        raise SchwabEvidenceAssemblyError(
            "quote evidence must be limited to current positions"
        )
    authority_by_quote = {item.quote_uid: item for item in session_authorities}
    if len(authority_by_quote) != len(session_authorities):
        raise SchwabEvidenceAssemblyError("session authorities contain duplicates")
    if set(authority_by_quote) != {item.quote_uid for item in capture.quotes}:
        raise SchwabEvidenceAssemblyError(
            "session authority must exactly cover quote evidence"
        )
    for normalized_quote in capture.quotes:
        validate_provider_session_authority_binding(
            authority_by_quote[normalized_quote.quote_uid],
            quote=normalized_quote,
            evaluated_at=capture.evaluated_at,
        )
    if any(assembled_at < item.evaluated_at for item in session_authorities):
        raise SchwabEvidenceAssemblyError("assembly precedes session authority")

    currencies = {item.identity.currency for item in snapshot.positions}
    currencies.update(item.currency for item in capture.quotes)
    order_records = tuple(
        _window_observation_record(
            record,
            window=window,
            identity_field="order_uid",
            observation_field="order_observation_uid",
        )
        for window in windows
        for record in window.order_records
    )
    transaction_records = tuple(
        _window_observation_record(
            record,
            window=window,
            identity_field="transaction_uid",
            observation_field="transaction_observation_uid",
        )
        for window in windows
        for record in window.transaction_records
    )
    lifecycle_event_records = tuple(
        _window_observation_record(
            record,
            window=window,
            identity_field="event_uid",
            observation_field="event_observation_uid",
        )
        for window in windows
        for record in window.lifecycle_events
    )
    lifecycle_event_leg_records = tuple(
        _window_observation_record(
            record,
            window=window,
            identity_field="event_leg_uid",
            observation_field="event_leg_observation_uid",
        )
        for window in windows
        for record in window.lifecycle_event_legs
    )
    fill_records = tuple(record for window in windows for record in window.transaction_rows)
    cash_records = tuple(
        _window_observation_record(
            record,
            window=window,
            identity_field="cash_uid",
            observation_field="cash_observation_uid",
        )
        for window in windows
        for record in window.cash_rows
    )
    currencies.update(
        str(record.get("currency", ""))
        for record in (*transaction_records, *fill_records, *cash_records)
        if str(record.get("currency", ""))
    )
    if len(currencies) != 1:
        raise SchwabEvidenceAssemblyError(
            "assembly requires one explicit native-currency consensus"
        )
    currency = next(iter(currencies))

    position_manifest = (position.external_manifest_sha256,)
    position_raw = (snapshot.raw_sha256,)
    lifecycle_manifests = tuple(window.external_manifest_sha256 for window in windows)
    lifecycle_raw = tuple(
        sha256(body).hexdigest()
        for window in windows
        for body in window.raw_response_bytes.values()
    )
    quote_manifest = (quote.external_manifest_sha256,)
    quote_raw = (capture.source.raw_sha256,)
    session_raw = tuple(item.raw_sha256 for item in session_authorities)
    order_excluded = sum(
        window.excluded_out_of_window_order_records for window in windows
    )
    fill_excluded = sum(
        window.excluded_out_of_window_order_fill_rows
        + window.excluded_out_of_window_transaction_fill_rows
        for window in windows
    )
    lifecycle_event_excluded = sum(
        window.excluded_out_of_window_lifecycle_events for window in windows
    )
    lifecycle_event_leg_excluded = sum(
        window.excluded_out_of_window_lifecycle_event_legs for window in windows
    )
    base_families = (
        _family(
            "account",
            source_manifest_sha256s=position_manifest,
            source_raw_sha256s=position_raw,
            source_record_count=1,
            records=(
                {
                    **dict(position.account_record),
                    "currency": currency,
                    "position_snapshot_uid": snapshot.snapshot_uid,
                    "account_complete": True,
                },
            ),
        ),
        _family(
            "positions",
            source_manifest_sha256s=position_manifest,
            source_raw_sha256s=position_raw,
            source_record_count=len(snapshot.positions),
            records=tuple(_position_record(item) for item in snapshot.positions),
        ),
        _family(
            "orders",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=len(order_records) + order_excluded,
            records=order_records,
            excluded_record_count=order_excluded,
            exclusion_reasons=("outside_approved_window",) if order_excluded else (),
        ),
        _family(
            "transactions",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=sum(window.transaction_stats.transactions for window in windows),
            records=transaction_records,
        ),
    )
    lifecycle_families = (
        _family(
            "lifecycle_events",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=(
                len(lifecycle_event_records) + lifecycle_event_excluded
            ),
            records=lifecycle_event_records,
            excluded_record_count=lifecycle_event_excluded,
            exclusion_reasons=(
                ("outside_approved_window",) if lifecycle_event_excluded else ()
            ),
        ),
        _family(
            "lifecycle_event_legs",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=(
                len(lifecycle_event_leg_records) + lifecycle_event_leg_excluded
            ),
            records=lifecycle_event_leg_records,
            excluded_record_count=lifecycle_event_leg_excluded,
            exclusion_reasons=(
                ("outside_approved_window",)
                if lifecycle_event_leg_excluded
                else ()
            ),
        ),
    )
    remaining_families = (
        _family(
            "fills",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=len(fill_records) + fill_excluded,
            records=fill_records,
            excluded_record_count=fill_excluded,
            exclusion_reasons=("outside_approved_window",) if fill_excluded else (),
        ),
        _family(
            "cash",
            source_manifest_sha256s=lifecycle_manifests,
            source_raw_sha256s=lifecycle_raw,
            source_record_count=len(cash_records),
            records=cash_records,
        ),
        _family(
            "quotes",
            source_manifest_sha256s=quote_manifest,
            source_raw_sha256s=quote_raw,
            source_record_count=len(capture.requests),
            records=tuple(asdict(item) for item in capture.quotes),
        ),
        _family(
            "sessions",
            source_manifest_sha256s=quote_manifest,
            source_raw_sha256s=session_raw,
            source_record_count=len(session_authorities),
            records=tuple(asdict(item) for item in session_authorities),
        ),
    )
    families = (
        base_families
        + (lifecycle_families if contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2 else ())
        + remaining_families
    )
    matched = sum(window.reconciliation.matched_rows for window in windows)
    order_only = sum(window.reconciliation.only_order_rows for window in windows)
    transaction_only = sum(
        window.reconciliation.only_transaction_rows for window in windows
    )
    cash_review_required = sum(
        1
        for record in cash_records
        if record.get("evidence_status") == "review_required"
    )
    reconciliation = SchwabEvidenceReconciliation(
        matched_fill_rows=matched,
        order_only_fill_rows=order_only,
        transaction_only_fill_rows=transaction_only,
        position_count=len(snapshot.positions),
        quote_count=len(capture.quotes),
        positions_without_quotes=len(position_keys - set(quote_by_key)),
        session_count=len(session_authorities),
        cash_review_required_rows=cash_review_required,
        all_positions_have_quotes=set(quote_by_key) == position_keys,
        all_quotes_have_session_authority=True,
    )
    candidate = SchwabPhase1EvidenceAssembly(
        assembly_uid="pending",
        contract_version=contract_version,
        provider="schwab",
        connection_uid=snapshot.connection_uid,
        source_account_id=snapshot.source_account_id,
        asof=snapshot.asof,
        assembled_at_utc=assembled_at,
        lifecycle_window_start=windows[0].window_start_date,
        lifecycle_window_end=windows[-1].window_end_date,
        families=families,
        reconciliation=reconciliation,
        final_status=(
            "ready"
            if order_only == 0 and transaction_only == 0 and fill_excluded == 0
            and cash_review_required == 0
            and (
                contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION
                or (
                    lifecycle_event_excluded == 0
                    and lifecycle_event_leg_excluded == 0
                    and all(
                        record.get("evidence_status") == "observed"
                        for record in lifecycle_event_leg_records
                    )
                )
            )
            else "review_required"
        ),
        result_fingerprint="pending",
    )
    fingerprint = calculate_schwab_evidence_assembly_fingerprint(candidate)
    assembly = replace(
        candidate,
        assembly_uid=f"schwab-evidence-assembly:{fingerprint}",
        result_fingerprint=fingerprint,
    )
    validate_schwab_phase1_evidence_assembly(assembly)
    return assembly


def schwab_phase1_evidence_assembly_bytes(
    assembly: SchwabPhase1EvidenceAssembly,
) -> bytes:
    validate_schwab_phase1_evidence_assembly(assembly)
    document = {
        "artifact_version": (
            SCHWAB_PHASE1_EVIDENCE_ARTIFACT_V2
            if assembly.contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
            else SCHWAB_PHASE1_EVIDENCE_ARTIFACT_VERSION
        ),
        "assembly_uid": assembly.assembly_uid,
        "result_fingerprint": assembly.result_fingerprint,
        **_assembly_payload(assembly),
    }
    return (_canonical_json(document) + "\n").encode("utf-8")


def load_schwab_phase1_evidence_assembly_bytes(
    body: bytes,
) -> SchwabPhase1EvidenceAssembly:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabEvidenceAssemblyError("assembly artifact is invalid JSON") from exc
    if not isinstance(document, dict):
        raise SchwabEvidenceAssemblyError("assembly artifact must be an object")
    artifact_version = document.get("artifact_version")
    if artifact_version not in {
        SCHWAB_PHASE1_EVIDENCE_ARTIFACT_VERSION,
        SCHWAB_PHASE1_EVIDENCE_ARTIFACT_V2,
    }:
        raise SchwabEvidenceAssemblyError("unsupported assembly artifact version")
    try:
        families = tuple(
            SchwabEvidenceFamily(
                family=item["family"],
                source_manifest_sha256s=tuple(item["source_manifest_sha256s"]),
                source_raw_sha256s=tuple(item["source_raw_sha256s"]),
                source_record_count=int(item["source_record_count"]),
                normalized_record_count=int(item["normalized_record_count"]),
                excluded_record_count=int(item["excluded_record_count"]),
                exclusion_reasons=tuple(item["exclusion_reasons"]),
                records=tuple(
                    freeze_schwab_evidence_value(record)
                    for record in item["records"]
                ),
                family_fingerprint=item["family_fingerprint"],
            )
            for item in document["families"]
        )
        reconciliation = SchwabEvidenceReconciliation(**document["reconciliation"])
        assembled_at = datetime.fromisoformat(document["assembled_at_utc"])
        assembly = SchwabPhase1EvidenceAssembly(
            assembly_uid=document["assembly_uid"],
            contract_version=document["contract_version"],
            provider=document["provider"],
            connection_uid=document["connection_uid"],
            source_account_id=document["source_account_id"],
            asof=date.fromisoformat(document["asof"]),
            assembled_at_utc=assembled_at,
            lifecycle_window_start=date.fromisoformat(document["lifecycle_window_start"]),
            lifecycle_window_end=date.fromisoformat(document["lifecycle_window_end"]),
            families=families,
            reconciliation=reconciliation,
            final_status=document["final_status"],
            result_fingerprint=document["result_fingerprint"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchwabEvidenceAssemblyError(
            "assembly artifact fields do not match the contract"
        ) from exc
    expected_artifact = (
        SCHWAB_PHASE1_EVIDENCE_ARTIFACT_V2
        if assembly.contract_version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
        else SCHWAB_PHASE1_EVIDENCE_ARTIFACT_VERSION
    )
    if artifact_version != expected_artifact:
        raise SchwabEvidenceAssemblyError(
            "assembly artifact and contract versions do not match"
        )
    validate_schwab_phase1_evidence_assembly(assembly)
    return assembly


def build_schwab_phase1_evidence_assembly_v2(**kwargs: Any) -> SchwabPhase1EvidenceAssembly:
    """Build the additive lifecycle-complete replacement assembly."""

    return build_schwab_phase1_evidence_assembly(
        **kwargs,
        contract_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    )


def privacy_safe_schwab_evidence_audit(
    assembly: SchwabPhase1EvidenceAssembly,
) -> Mapping[str, Any]:
    validate_schwab_phase1_evidence_assembly(assembly)
    return MappingProxyType(
        {
            "contract_version": assembly.contract_version,
            "assembly_uid": assembly.assembly_uid,
            "result_fingerprint": assembly.result_fingerprint,
            "account_scope_sha256": sha256(
                assembly.source_account_id.encode("utf-8")
            ).hexdigest(),
            "asof": assembly.asof.isoformat(),
            "final_status": assembly.final_status,
            "family_counts": {
                family.family: family.normalized_record_count
                for family in assembly.families
            },
            "matched_fill_rows": assembly.reconciliation.matched_fill_rows,
            "order_only_fill_rows": assembly.reconciliation.order_only_fill_rows,
            "transaction_only_fill_rows": (
                assembly.reconciliation.transaction_only_fill_rows
            ),
            "cash_review_required_rows": (
                assembly.reconciliation.cash_review_required_rows
            ),
            "positions_without_quotes": (
                assembly.reconciliation.positions_without_quotes
            ),
        }
    )
