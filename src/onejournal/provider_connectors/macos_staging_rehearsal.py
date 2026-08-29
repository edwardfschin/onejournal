"""Provider-disabled macOS staging rehearsal with no external side effects.

The probe reads only its checked-in policy and emits a secret-free result to stdout
through the operator script. It does not construct a Keychain runner, acquire a
credential, open a listener, access a database, call a provider, or write evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from onejournal.provider_connectors.macos_staging import (
    MACOS_STAGING_CONTRACT_VERSION,
    MacOSStagingError,
    load_macos_staging_policy,
)


MACOS_STAGING_REHEARSAL_CONTRACT_VERSION = "onejournal.macos-staging-rehearsal.v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class MacOSStagingRehearsalError(ValueError):
    """Raised when a provider-disabled rehearsal cannot be proven."""


@dataclass(frozen=True)
class MacOSStagingRehearsal:
    """Secret-free result for the exact process that executed this probe."""

    contract_version: str
    artifact_commit: str
    host_uid: str
    observed_at_utc: datetime
    policy_contract_version: str
    policy_sha256: str
    target: str
    keychain_accessed: bool
    credential_installation_enabled: bool
    provider_calls_enabled: bool
    token_refresh_enabled: bool
    public_listener_enabled: bool
    journal_database_mounted: bool
    raw_evidence_written: bool
    final_status: str


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise MacOSStagingRehearsalError(f"{field} must be a secret-safe opaque identifier")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MacOSStagingRehearsalError(f"{field} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise MacOSStagingRehearsalError(f"{field} must be expressed in UTC")
    return value.astimezone(UTC)


def run_macos_provider_staging_rehearsal(
    *,
    policy_path: Path,
    artifact_commit: str,
    host_uid: str,
    observed_at_utc: datetime,
) -> MacOSStagingRehearsal:
    """Prove this probe ran against an entirely disabled staging configuration."""

    if not isinstance(artifact_commit, str) or not _GIT_SHA.fullmatch(artifact_commit):
        raise MacOSStagingRehearsalError("artifact_commit must be a full lowercase Git SHA")
    checked_host_uid = _safe_id(host_uid, "host_uid")
    observed = _utc(observed_at_utc, "observed_at_utc")
    try:
        policy_bytes = policy_path.read_bytes()
    except OSError as exc:
        raise MacOSStagingRehearsalError("staging policy is unavailable") from exc
    try:
        policy = load_macos_staging_policy(policy_path)
    except MacOSStagingError as exc:
        raise MacOSStagingRehearsalError("staging policy failed validation") from exc
    if policy.contract_version != MACOS_STAGING_CONTRACT_VERSION:
        raise MacOSStagingRehearsalError("unsupported staging policy contract")
    if any(
        (
            policy.enabled,
            policy.credential_installation_enabled,
            policy.provider_calls_enabled,
            policy.token_refresh_enabled,
            policy.public_listener_enabled,
            policy.journal_database_mounted,
        )
    ):
        raise MacOSStagingRehearsalError(
            "provider-disabled rehearsal requires every staging capability disabled"
        )
    return MacOSStagingRehearsal(
        contract_version=MACOS_STAGING_REHEARSAL_CONTRACT_VERSION,
        artifact_commit=artifact_commit,
        host_uid=checked_host_uid,
        observed_at_utc=observed,
        policy_contract_version=policy.contract_version,
        policy_sha256=sha256(policy_bytes).hexdigest(),
        target=policy.target,
        keychain_accessed=False,
        credential_installation_enabled=False,
        provider_calls_enabled=False,
        token_refresh_enabled=False,
        public_listener_enabled=False,
        journal_database_mounted=False,
        raw_evidence_written=False,
        final_status="provider_disabled_rehearsal_passed",
    )


def macos_staging_rehearsal_bytes(result: MacOSStagingRehearsal) -> bytes:
    """Serialize a canonical secret-free rehearsal result for stdout only."""

    if not isinstance(result, MacOSStagingRehearsal):
        raise MacOSStagingRehearsalError("unsupported rehearsal result")
    if result.contract_version != MACOS_STAGING_REHEARSAL_CONTRACT_VERSION:
        raise MacOSStagingRehearsalError("unsupported rehearsal contract")
    _safe_id(result.host_uid, "host_uid")
    if not isinstance(result.artifact_commit, str) or not _GIT_SHA.fullmatch(
        result.artifact_commit
    ):
        raise MacOSStagingRehearsalError("artifact_commit must be a full lowercase Git SHA")
    observed = _utc(result.observed_at_utc, "observed_at_utc")
    if (
        result.policy_contract_version != MACOS_STAGING_CONTRACT_VERSION
        or result.target != "local_macos"
        or result.final_status != "provider_disabled_rehearsal_passed"
    ):
        raise MacOSStagingRehearsalError("rehearsal result does not bind the staging policy")
    if any(
        (
            result.keychain_accessed,
            result.credential_installation_enabled,
            result.provider_calls_enabled,
            result.token_refresh_enabled,
            result.public_listener_enabled,
            result.journal_database_mounted,
            result.raw_evidence_written,
        )
    ):
        raise MacOSStagingRehearsalError("rehearsal result contains an enabled capability")
    payload = asdict(result)
    payload["observed_at_utc"] = observed.isoformat().replace("+00:00", "Z")
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
