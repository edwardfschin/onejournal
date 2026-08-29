"""Credential-free validation for provider-connection owner cutovers.

This module validates secret-free observations supplied by an external operator. It
does not inspect processes, access credentials, call a provider, change configuration,
or activate either owner. Operational evidence remains authoritative outside this
pure contract boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re


PROVIDER_CONNECTION_CUTOVER_CONTRACT_VERSION = (
    "onejournal.provider-connection-cutover.v1"
)
PROVIDER_CONNECTION_CUTOVER_PHASES = (
    "source_active",
    "owner_gap",
    "target_provisioned_disabled",
    "target_active",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderConnectionCutoverError(ValueError):
    """Raised when single-owner cutover evidence fails closed."""


@dataclass(frozen=True)
class ProviderOwnerCapabilityState:
    """Secret-free capability state for one connection owner."""

    owner_uid: str
    host_uid: str
    owner_epoch_uid: str | None
    credential_generation_uid: str | None
    credential_accessible: bool
    provider_call_enabled: bool
    token_refresh_enabled: bool


@dataclass(frozen=True)
class ProviderConnectionCutoverObservation:
    """One externally established owner-boundary observation."""

    phase: str
    observed_at_utc: datetime
    source: ProviderOwnerCapabilityState
    target: ProviderOwnerCapabilityState
    evidence_sha256: str


@dataclass(frozen=True)
class ProviderConnectionCutoverEvidence:
    """Ordered, secret-free evidence for a forward cutover or rollback."""

    contract_version: str
    cutover_uid: str
    direction: str
    provider: str
    connection_uid: str
    approval_id: str
    hosted_data_authorization_id: str
    provider_usage_acknowledgement_uid: str
    target_public_listener_enabled: bool
    target_journal_database_mounted: bool
    observations: tuple[ProviderConnectionCutoverObservation, ...]


@dataclass(frozen=True)
class ProviderConnectionCutoverValidation:
    """Result of contract validation, not operational acceptance."""

    cutover_uid: str
    direction: str
    provider: str
    connection_uid: str
    source_owner_uid: str
    target_owner_uid: str
    target_owner_epoch_uid: str
    target_credential_generation_uid: str
    observed_at_utc: datetime


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ProviderConnectionCutoverError(
            f"{field} must be a secret-safe opaque identifier"
        )
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProviderConnectionCutoverError(f"{field} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ProviderConnectionCutoverError(f"{field} must be expressed in UTC")
    return value.astimezone(UTC)


def _bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProviderConnectionCutoverError(f"{field} must be a boolean")
    return value


def _validate_state(state: ProviderOwnerCapabilityState, field: str) -> None:
    if not isinstance(state, ProviderOwnerCapabilityState):
        raise ProviderConnectionCutoverError(f"{field} has an unsupported state")
    _safe_id(state.owner_uid, f"{field}.owner_uid")
    _safe_id(state.host_uid, f"{field}.host_uid")
    if state.owner_epoch_uid is not None:
        _safe_id(state.owner_epoch_uid, f"{field}.owner_epoch_uid")
    if state.credential_generation_uid is not None:
        _safe_id(
            state.credential_generation_uid,
            f"{field}.credential_generation_uid",
        )
    _bool(state.credential_accessible, f"{field}.credential_accessible")
    _bool(state.provider_call_enabled, f"{field}.provider_call_enabled")
    _bool(state.token_refresh_enabled, f"{field}.token_refresh_enabled")
    if (
        state.provider_call_enabled or state.token_refresh_enabled
    ) and not state.credential_accessible:
        raise ProviderConnectionCutoverError(
            f"{field} cannot call or refresh without credential access"
        )
    if state.credential_accessible and (
        state.owner_epoch_uid is None or state.credential_generation_uid is None
    ):
        raise ProviderConnectionCutoverError(
            f"{field} credential access requires owner and generation lineage"
        )


def _disabled(state: ProviderOwnerCapabilityState) -> bool:
    return not (
        state.credential_accessible
        or state.provider_call_enabled
        or state.token_refresh_enabled
    )


def _active(state: ProviderOwnerCapabilityState) -> bool:
    return (
        state.credential_accessible
        and state.provider_call_enabled
        and state.token_refresh_enabled
    )


def validate_provider_connection_cutover(
    evidence: ProviderConnectionCutoverEvidence,
) -> ProviderConnectionCutoverValidation:
    """Validate an exact break-before-make sequence without performing it."""

    if not isinstance(evidence, ProviderConnectionCutoverEvidence):
        raise ProviderConnectionCutoverError("cutover evidence has an unsupported type")
    if evidence.contract_version != PROVIDER_CONNECTION_CUTOVER_CONTRACT_VERSION:
        raise ProviderConnectionCutoverError("unsupported cutover contract version")
    _safe_id(evidence.cutover_uid, "cutover_uid")
    if evidence.direction not in {"forward", "rollback"}:
        raise ProviderConnectionCutoverError("direction must be forward or rollback")
    if not isinstance(evidence.provider, str) or not _PROVIDER.fullmatch(evidence.provider):
        raise ProviderConnectionCutoverError("provider must be a normalized identifier")
    _safe_id(evidence.connection_uid, "connection_uid")
    _safe_id(evidence.approval_id, "approval_id")
    _safe_id(evidence.hosted_data_authorization_id, "hosted_data_authorization_id")
    _safe_id(
        evidence.provider_usage_acknowledgement_uid,
        "provider_usage_acknowledgement_uid",
    )
    if _bool(
        evidence.target_public_listener_enabled,
        "target_public_listener_enabled",
    ):
        raise ProviderConnectionCutoverError("target must not expose a public listener")
    if _bool(
        evidence.target_journal_database_mounted,
        "target_journal_database_mounted",
    ):
        raise ProviderConnectionCutoverError(
            "target must not mount the operational journal database"
        )
    if len(evidence.observations) != len(PROVIDER_CONNECTION_CUTOVER_PHASES):
        raise ProviderConnectionCutoverError("cutover requires exactly four observations")

    observed_phases = tuple(item.phase for item in evidence.observations)
    if observed_phases != PROVIDER_CONNECTION_CUTOVER_PHASES:
        raise ProviderConnectionCutoverError("cutover phases are missing or out of order")

    times: list[datetime] = []
    hashes: set[str] = set()
    for index, item in enumerate(evidence.observations):
        field = f"observations[{index}]"
        if not isinstance(item, ProviderConnectionCutoverObservation):
            raise ProviderConnectionCutoverError(f"{field} has an unsupported type")
        times.append(_utc(item.observed_at_utc, f"{field}.observed_at_utc"))
        _validate_state(item.source, f"{field}.source")
        _validate_state(item.target, f"{field}.target")
        if not isinstance(item.evidence_sha256, str) or not _SHA256.fullmatch(
            item.evidence_sha256
        ):
            raise ProviderConnectionCutoverError(
                f"{field}.evidence_sha256 must be lowercase SHA-256"
            )
        if item.evidence_sha256 in hashes:
            raise ProviderConnectionCutoverError("observation evidence hashes must be unique")
        hashes.add(item.evidence_sha256)
        if item.source.owner_uid == item.target.owner_uid:
            raise ProviderConnectionCutoverError("source and target owners must be distinct")
        if item.source.host_uid == item.target.host_uid:
            raise ProviderConnectionCutoverError("source and target hosts must be distinct")
        if item.source.credential_accessible and item.target.credential_accessible:
            raise ProviderConnectionCutoverError("dual credential ownership is forbidden")

    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ProviderConnectionCutoverError("cutover observations must be strictly ordered")

    source_owner_uids = {item.source.owner_uid for item in evidence.observations}
    target_owner_uids = {item.target.owner_uid for item in evidence.observations}
    source_host_uids = {item.source.host_uid for item in evidence.observations}
    target_host_uids = {item.target.host_uid for item in evidence.observations}
    if any(len(values) != 1 for values in (
        source_owner_uids,
        target_owner_uids,
        source_host_uids,
        target_host_uids,
    )):
        raise ProviderConnectionCutoverError("owner and host identities must remain stable")

    source_active, owner_gap, target_provisioned, target_active = evidence.observations
    if not _active(source_active.source) or not _disabled(source_active.target):
        raise ProviderConnectionCutoverError("source_active capabilities are invalid")
    if not _disabled(owner_gap.source) or not _disabled(owner_gap.target):
        raise ProviderConnectionCutoverError("owner_gap must disable both owners")
    if not _disabled(target_provisioned.source):
        raise ProviderConnectionCutoverError("source must remain retired after owner_gap")
    if not target_provisioned.target.credential_accessible or (
        target_provisioned.target.provider_call_enabled
        or target_provisioned.target.token_refresh_enabled
    ):
        raise ProviderConnectionCutoverError(
            "target must be provisioned while provider calls and refresh remain disabled"
        )
    if not _disabled(target_active.source) or not _active(target_active.target):
        raise ProviderConnectionCutoverError("target_active capabilities are invalid")

    source_epoch = source_active.source.owner_epoch_uid
    source_generation = source_active.source.credential_generation_uid
    target_epoch = target_provisioned.target.owner_epoch_uid
    target_generation = target_provisioned.target.credential_generation_uid
    if source_epoch is None or source_generation is None:
        raise ProviderConnectionCutoverError("source lineage is incomplete")
    if target_epoch is None or target_generation is None:
        raise ProviderConnectionCutoverError("target lineage is incomplete")
    if target_epoch == source_epoch or target_generation == source_generation:
        raise ProviderConnectionCutoverError(
            "target must use a new owner epoch and credential generation"
        )
    if (
        target_active.target.owner_epoch_uid != target_epoch
        or target_active.target.credential_generation_uid != target_generation
    ):
        raise ProviderConnectionCutoverError(
            "target lineage changed between provisioning and activation"
        )
    if any(
        item.source.owner_epoch_uid != source_epoch
        or item.source.credential_generation_uid != source_generation
        for item in evidence.observations
    ):
        raise ProviderConnectionCutoverError("source lineage must remain auditable")
    if any(
        item.target.owner_epoch_uid is not None
        or item.target.credential_generation_uid is not None
        for item in (source_active, owner_gap)
    ):
        raise ProviderConnectionCutoverError(
            "target must not be provisioned before the owner_gap completes"
        )

    return ProviderConnectionCutoverValidation(
        cutover_uid=evidence.cutover_uid,
        direction=evidence.direction,
        provider=evidence.provider,
        connection_uid=evidence.connection_uid,
        source_owner_uid=source_active.source.owner_uid,
        target_owner_uid=target_active.target.owner_uid,
        target_owner_epoch_uid=target_epoch,
        target_credential_generation_uid=target_generation,
        observed_at_utc=times[-1],
    )
