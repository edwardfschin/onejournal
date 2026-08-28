"""Fail-closed provider-use and raw-evidence lifecycle contracts.

This module is deliberately credential-, network-, database-, and UI-free. A future
provider connector must validate an externally persisted acknowledgement through this
boundary before retrieval. The acknowledgement is a declaration, never entitlement
evidence; provider-reported entitlement remains mandatory downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

import yaml


PROVIDER_USAGE_POLICY_CONTRACT_VERSION = "onejournal.provider-usage-policy.v1"
PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION = (
    "onejournal.provider-usage-acknowledgement.v1"
)
PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA = (
    "onejournal.provider-usage-acknowledgement-artifact.v1"
)
RAW_EVIDENCE_LIFECYCLE_MODE = (
    "retain_until_explicit_approved_deletion_or_provider_requirement"
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACKNOWLEDGEMENT_FIELDS = {
    "contract_version",
    "acknowledgement_uid",
    "provider",
    "connection_uid",
    "terms_profile_id",
    "notice_version",
    "operating_scope",
    "accepted_at_utc",
    "product_version",
    "raw_evidence_policy_id",
    "declarations",
}
_REQUIRED_PROFILE_FIELDS = {
    "profile_id",
    "notice_version",
    "operating_scope",
    "permitted_use",
    "reviewed_at_utc",
    "official_terms",
    "requires_authenticated_provider_terms_confirmation",
    "provider_reported_entitlement_required",
    "redistribution_allowed",
    "public_display_allowed",
    "hosted_storage_allowed",
    "required_declarations",
    "raw_evidence_lifecycle",
}
_REQUIRED_RAW_LIFECYCLE_FIELDS = {
    "policy_id",
    "mode",
    "automatic_deletion_enabled",
    "fixed_retention_period_days",
    "deletion_requires_explicit_approval",
    "deletion_audit_required",
    "provider_rule_change_requires_new_profile",
}
_REQUIRED_DECLARATIONS = frozenset(
    {
        "authorized_connection",
        "applicable_terms_accepted",
        "authenticated_provider_terms_reviewed",
        "required_entitlements_maintained",
        "personal_noncommercial_use_only",
        "no_redistribution_or_public_exposure",
        "onejournal_does_not_grant_market_data_rights",
        "raw_evidence_lifecycle_accepted",
    }
)


class ProviderUsagePolicyError(ValueError):
    """Raised when provider-use authorization cannot be proven."""


@dataclass(frozen=True)
class TermsReference:
    reference_id: str
    title: str
    url: str


@dataclass(frozen=True)
class RawEvidenceLifecyclePolicy:
    policy_id: str
    mode: str
    automatic_deletion_enabled: bool
    fixed_retention_period_days: int | None
    deletion_requires_explicit_approval: bool
    deletion_audit_required: bool
    provider_rule_change_requires_new_profile: bool


@dataclass(frozen=True)
class ProviderTermsProfile:
    provider: str
    profile_id: str
    notice_version: str
    operating_scope: str
    permitted_use: str
    reviewed_at_utc: datetime
    official_terms: tuple[TermsReference, ...]
    requires_authenticated_provider_terms_confirmation: bool
    provider_reported_entitlement_required: bool
    redistribution_allowed: bool
    public_display_allowed: bool
    hosted_storage_allowed: bool
    required_declarations: frozenset[str]
    raw_evidence_lifecycle: RawEvidenceLifecyclePolicy


@dataclass(frozen=True)
class ProviderUsagePolicy:
    contract_version: str
    active_profiles: Mapping[str, ProviderTermsProfile]


@dataclass(frozen=True)
class ProviderUsageAcknowledgement:
    contract_version: str
    acknowledgement_uid: str
    provider: str
    connection_uid: str
    terms_profile_id: str
    notice_version: str
    operating_scope: str
    accepted_at_utc: datetime
    product_version: str
    raw_evidence_policy_id: str
    declarations: frozenset[str]


@dataclass(frozen=True)
class ProviderUsageAuthorization:
    provider: str
    connection_uid: str
    acknowledgement_uid: str
    terms_profile_id: str
    raw_evidence_lifecycle: RawEvidenceLifecyclePolicy
    provider_reported_entitlement_required: bool


@dataclass(frozen=True)
class ProviderUsageAcknowledgementArtifact:
    """Canonical private acknowledgement plus its owner-approval reference."""

    schema: str
    creation_approval_id: str
    acknowledgement: ProviderUsageAcknowledgement


@dataclass(frozen=True)
class RawEvidenceDeletionAuthorization:
    deletion_authorization_uid: str
    provider: str
    connection_uid: str
    acknowledgement_uid: str
    raw_evidence_policy_id: str
    approval_id: str
    authorized_at_utc: datetime


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ProviderUsagePolicyError(f"{field} must be a mapping")
    return value


def _require_exact_fields(
    value: Mapping[str, object], *, field: str, expected: set[str]
) -> None:
    if set(value) != expected:
        raise ProviderUsagePolicyError(f"{field} fields do not match the contract")


def _require_safe_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ProviderUsagePolicyError(f"{field} must be a secret-safe opaque identifier")
    return value


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProviderUsagePolicyError(f"{field} must be a non-empty trimmed string")
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise ProviderUsagePolicyError(f"{field} must be a boolean")
    return value


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProviderUsagePolicyError(f"{field} must be an ISO-8601 UTC instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderUsagePolicyError(
            f"{field} must be an ISO-8601 UTC instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderUsagePolicyError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _require_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderUsagePolicyError(f"{field} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ProviderUsagePolicyError(f"{field} must be expressed in UTC")
    return value.astimezone(UTC)


def _load_terms_references(value: object, *, provider: str) -> tuple[TermsReference, ...]:
    if not isinstance(value, list) or not value:
        raise ProviderUsagePolicyError(
            f"provider_usage.active_profiles.{provider}.official_terms must be non-empty"
        )
    references: list[TermsReference] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        field = f"provider_usage.active_profiles.{provider}.official_terms[{index}]"
        mapping = _require_mapping(item, field=field)
        _require_exact_fields(
            mapping,
            field=field,
            expected={"reference_id", "title", "url"},
        )
        reference_id = _require_safe_id(
            mapping["reference_id"], field=f"{field}.reference_id"
        )
        if reference_id in seen:
            raise ProviderUsagePolicyError(f"duplicate terms reference: {reference_id}")
        seen.add(reference_id)
        url = _require_string(mapping["url"], field=f"{field}.url")
        if not url.startswith("https://"):
            raise ProviderUsagePolicyError(f"{field}.url must use https")
        references.append(
            TermsReference(
                reference_id=reference_id,
                title=_require_string(mapping["title"], field=f"{field}.title"),
                url=url,
            )
        )
    return tuple(references)


def _load_raw_lifecycle(
    value: object, *, provider: str
) -> RawEvidenceLifecyclePolicy:
    field = f"provider_usage.active_profiles.{provider}.raw_evidence_lifecycle"
    mapping = _require_mapping(value, field=field)
    _require_exact_fields(mapping, field=field, expected=_REQUIRED_RAW_LIFECYCLE_FIELDS)
    fixed_days = mapping["fixed_retention_period_days"]
    if fixed_days is not None and (type(fixed_days) is not int or fixed_days <= 0):
        raise ProviderUsagePolicyError(
            f"{field}.fixed_retention_period_days must be null or a positive integer"
        )
    policy = RawEvidenceLifecyclePolicy(
        policy_id=_require_safe_id(mapping["policy_id"], field=f"{field}.policy_id"),
        mode=_require_string(mapping["mode"], field=f"{field}.mode"),
        automatic_deletion_enabled=_require_bool(
            mapping["automatic_deletion_enabled"],
            field=f"{field}.automatic_deletion_enabled",
        ),
        fixed_retention_period_days=fixed_days,
        deletion_requires_explicit_approval=_require_bool(
            mapping["deletion_requires_explicit_approval"],
            field=f"{field}.deletion_requires_explicit_approval",
        ),
        deletion_audit_required=_require_bool(
            mapping["deletion_audit_required"],
            field=f"{field}.deletion_audit_required",
        ),
        provider_rule_change_requires_new_profile=_require_bool(
            mapping["provider_rule_change_requires_new_profile"],
            field=f"{field}.provider_rule_change_requires_new_profile",
        ),
    )
    if (
        policy.mode != RAW_EVIDENCE_LIFECYCLE_MODE
        or policy.automatic_deletion_enabled
        or policy.fixed_retention_period_days is not None
        or not policy.deletion_requires_explicit_approval
        or not policy.deletion_audit_required
        or not policy.provider_rule_change_requires_new_profile
    ):
        raise ProviderUsagePolicyError(
            f"{field} weakens the approved local-owner lifecycle policy"
        )
    return policy


def load_provider_usage_policy(path: Path) -> ProviderUsagePolicy:
    """Load the strict provider-use section from repository configuration."""

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProviderUsagePolicyError(f"cannot load provider usage policy: {path}") from exc
    root = _require_mapping(loaded, field="root")
    marketdata = _require_mapping(root.get("marketdata"), field="marketdata")
    usage = _require_mapping(
        marketdata.get("provider_usage"), field="marketdata.provider_usage"
    )
    _require_exact_fields(
        usage,
        field="marketdata.provider_usage",
        expected={"contract_version", "active_profiles"},
    )
    if usage["contract_version"] != PROVIDER_USAGE_POLICY_CONTRACT_VERSION:
        raise ProviderUsagePolicyError("unsupported provider usage policy contract version")
    active = _require_mapping(
        usage["active_profiles"], field="marketdata.provider_usage.active_profiles"
    )
    if not active:
        raise ProviderUsagePolicyError("provider usage policy has no active profiles")

    profiles: dict[str, ProviderTermsProfile] = {}
    for provider_key, item in active.items():
        provider = _require_string(provider_key, field="provider key").lower()
        if provider != provider_key:
            raise ProviderUsagePolicyError("provider keys must be lowercase")
        field = f"marketdata.provider_usage.active_profiles.{provider}"
        mapping = _require_mapping(item, field=field)
        _require_exact_fields(mapping, field=field, expected=_REQUIRED_PROFILE_FIELDS)
        declarations_value = mapping["required_declarations"]
        if not isinstance(declarations_value, list) or not all(
            isinstance(item, str) for item in declarations_value
        ):
            raise ProviderUsagePolicyError(f"{field}.required_declarations must be a list")
        declarations = frozenset(declarations_value)
        if declarations != _REQUIRED_DECLARATIONS or len(declarations_value) != len(
            declarations
        ):
            raise ProviderUsagePolicyError(
                f"{field}.required_declarations weakens or duplicates the contract"
            )
        profile = ProviderTermsProfile(
            provider=provider,
            profile_id=_require_safe_id(
                mapping["profile_id"], field=f"{field}.profile_id"
            ),
            notice_version=_require_safe_id(
                mapping["notice_version"], field=f"{field}.notice_version"
            ),
            operating_scope=_require_string(
                mapping["operating_scope"], field=f"{field}.operating_scope"
            ),
            permitted_use=_require_string(
                mapping["permitted_use"], field=f"{field}.permitted_use"
            ),
            reviewed_at_utc=_parse_utc(
                mapping["reviewed_at_utc"], field=f"{field}.reviewed_at_utc"
            ),
            official_terms=_load_terms_references(
                mapping["official_terms"], provider=provider
            ),
            requires_authenticated_provider_terms_confirmation=_require_bool(
                mapping["requires_authenticated_provider_terms_confirmation"],
                field=f"{field}.requires_authenticated_provider_terms_confirmation",
            ),
            provider_reported_entitlement_required=_require_bool(
                mapping["provider_reported_entitlement_required"],
                field=f"{field}.provider_reported_entitlement_required",
            ),
            redistribution_allowed=_require_bool(
                mapping["redistribution_allowed"],
                field=f"{field}.redistribution_allowed",
            ),
            public_display_allowed=_require_bool(
                mapping["public_display_allowed"],
                field=f"{field}.public_display_allowed",
            ),
            hosted_storage_allowed=_require_bool(
                mapping["hosted_storage_allowed"],
                field=f"{field}.hosted_storage_allowed",
            ),
            required_declarations=declarations,
            raw_evidence_lifecycle=_load_raw_lifecycle(
                mapping["raw_evidence_lifecycle"], provider=provider
            ),
        )
        if (
            profile.operating_scope != "owner_operated_local_connection"
            or profile.permitted_use != "personal_noncommercial"
            or not profile.requires_authenticated_provider_terms_confirmation
            or not profile.provider_reported_entitlement_required
            or profile.redistribution_allowed
            or profile.public_display_allowed
            or profile.hosted_storage_allowed
        ):
            raise ProviderUsagePolicyError(f"{field} exceeds the approved operating scope")
        profiles[provider] = profile

    return ProviderUsagePolicy(
        contract_version=PROVIDER_USAGE_POLICY_CONTRACT_VERSION,
        active_profiles=MappingProxyType(profiles),
    )


def _acknowledgement_identity_payload(
    acknowledgement: ProviderUsageAcknowledgement,
) -> dict[str, object]:
    return {
        "contract_version": acknowledgement.contract_version,
        "provider": acknowledgement.provider,
        "connection_uid": acknowledgement.connection_uid,
        "terms_profile_id": acknowledgement.terms_profile_id,
        "notice_version": acknowledgement.notice_version,
        "operating_scope": acknowledgement.operating_scope,
        "accepted_at_utc": acknowledgement.accepted_at_utc.isoformat().replace(
            "+00:00", "Z"
        ),
        "product_version": acknowledgement.product_version,
        "raw_evidence_policy_id": acknowledgement.raw_evidence_policy_id,
        "declarations": sorted(acknowledgement.declarations),
    }


def build_provider_usage_acknowledgement_uid(
    acknowledgement: ProviderUsageAcknowledgement,
) -> str:
    """Build the deterministic append-only identity for an acknowledgement."""

    _require_utc(acknowledgement.accepted_at_utc, field="accepted_at_utc")
    payload = json.dumps(
        _acknowledgement_identity_payload(acknowledgement),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"provider-usage-ack:{sha256(payload).hexdigest()}"


def provider_usage_acknowledgement_artifact_bytes(
    acknowledgement: ProviderUsageAcknowledgement,
    *,
    creation_approval_id: str,
) -> bytes:
    """Serialize one canonical, deterministic, secret-free private artifact."""

    approval_id = _require_safe_id(
        creation_approval_id, field="creation_approval_id"
    )
    expected_uid = build_provider_usage_acknowledgement_uid(acknowledgement)
    if acknowledgement.acknowledgement_uid != expected_uid:
        raise ProviderUsagePolicyError("acknowledgement identity mismatch")
    document = {
        "schema": PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA,
        "creation_approval_id": approval_id,
        "acknowledgement": {
            **_acknowledgement_identity_payload(acknowledgement),
            "acknowledgement_uid": acknowledgement.acknowledgement_uid,
        },
    }
    return (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def load_provider_usage_acknowledgement_artifact_bytes(
    body: bytes,
    *,
    policy: ProviderUsagePolicy,
    expected_provider: str,
    expected_connection_uid: str,
    evaluated_at_utc: datetime,
    expected_sha256: str | None = None,
) -> tuple[ProviderUsageAcknowledgementArtifact, ProviderUsageAuthorization]:
    """Load, checksum, canonicalize, and authorize one private artifact."""

    if not isinstance(body, bytes) or not body or len(body) > 64 * 1024:
        raise ProviderUsagePolicyError("acknowledgement artifact byte size is invalid")
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(
            expected_sha256
        ):
            raise ProviderUsagePolicyError(
                "expected acknowledgement artifact SHA-256 is invalid"
            )
        if sha256(body).hexdigest() != expected_sha256:
            raise ProviderUsagePolicyError(
                "acknowledgement artifact checksum mismatch"
            )
    try:
        document = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProviderUsagePolicyError(
            "acknowledgement artifact is not finite JSON"
        ) from exc
    root = _require_mapping(document, field="acknowledgement artifact")
    _require_exact_fields(
        root,
        field="acknowledgement artifact",
        expected={"schema", "creation_approval_id", "acknowledgement"},
    )
    if root["schema"] != PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA:
        raise ProviderUsagePolicyError("unsupported acknowledgement artifact schema")
    approval_id = _require_safe_id(
        root["creation_approval_id"], field="creation_approval_id"
    )
    payload = _require_mapping(
        root["acknowledgement"], field="acknowledgement"
    )
    _require_exact_fields(
        payload,
        field="acknowledgement",
        expected=_ACKNOWLEDGEMENT_FIELDS,
    )
    declarations_value = payload["declarations"]
    if not isinstance(declarations_value, list) or not all(
        isinstance(value, str) for value in declarations_value
    ):
        raise ProviderUsagePolicyError(
            "acknowledgement declarations must be a string array"
        )
    declarations = frozenset(declarations_value)
    if len(declarations) != len(declarations_value):
        raise ProviderUsagePolicyError("acknowledgement declarations contain duplicates")
    acknowledgement = ProviderUsageAcknowledgement(
        contract_version=_require_string(
            payload["contract_version"], field="contract_version"
        ),
        acknowledgement_uid=_require_safe_id(
            payload["acknowledgement_uid"], field="acknowledgement_uid"
        ),
        provider=_require_string(payload["provider"], field="provider"),
        connection_uid=_require_safe_id(
            payload["connection_uid"], field="connection_uid"
        ),
        terms_profile_id=_require_safe_id(
            payload["terms_profile_id"], field="terms_profile_id"
        ),
        notice_version=_require_safe_id(
            payload["notice_version"], field="notice_version"
        ),
        operating_scope=_require_string(
            payload["operating_scope"], field="operating_scope"
        ),
        accepted_at_utc=_parse_utc(
            payload["accepted_at_utc"], field="accepted_at_utc"
        ),
        product_version=_require_string(
            payload["product_version"], field="product_version"
        ),
        raw_evidence_policy_id=_require_safe_id(
            payload["raw_evidence_policy_id"], field="raw_evidence_policy_id"
        ),
        declarations=declarations,
    )
    authorization = validate_provider_usage_acknowledgement(
        acknowledgement,
        policy=policy,
        expected_provider=expected_provider,
        expected_connection_uid=expected_connection_uid,
        evaluated_at_utc=evaluated_at_utc,
    )
    artifact = ProviderUsageAcknowledgementArtifact(
        schema=PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA,
        creation_approval_id=approval_id,
        acknowledgement=acknowledgement,
    )
    if body != provider_usage_acknowledgement_artifact_bytes(
        acknowledgement,
        creation_approval_id=approval_id,
    ):
        raise ProviderUsagePolicyError(
            "acknowledgement artifact bytes are not canonical"
        )
    return artifact, authorization


def validate_provider_usage_acknowledgement(
    acknowledgement: ProviderUsageAcknowledgement,
    *,
    policy: ProviderUsagePolicy,
    expected_provider: str,
    expected_connection_uid: str,
    evaluated_at_utc: datetime,
) -> ProviderUsageAuthorization:
    """Authorize only an exact current provider/connection acknowledgement."""

    evaluated_at = _require_utc(evaluated_at_utc, field="evaluated_at_utc")
    accepted_at = _require_utc(
        acknowledgement.accepted_at_utc, field="accepted_at_utc"
    )
    if acknowledgement.contract_version != PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION:
        raise ProviderUsagePolicyError("unsupported acknowledgement contract version")
    request_provider = _require_string(
        expected_provider, field="expected_provider"
    ).lower()
    if request_provider != expected_provider:
        raise ProviderUsagePolicyError("expected_provider must be lowercase")
    request_connection = _require_safe_id(
        expected_connection_uid, field="expected_connection_uid"
    )
    provider = _require_string(acknowledgement.provider, field="provider").lower()
    if provider != acknowledgement.provider:
        raise ProviderUsagePolicyError("provider must be lowercase")
    _require_safe_id(acknowledgement.connection_uid, field="connection_uid")
    if provider != request_provider:
        raise ProviderUsagePolicyError("acknowledgement provider mismatch")
    if acknowledgement.connection_uid != request_connection:
        raise ProviderUsagePolicyError("acknowledgement connection mismatch")
    _require_string(acknowledgement.product_version, field="product_version")
    profile = policy.active_profiles.get(provider)
    if profile is None:
        raise ProviderUsagePolicyError("provider has no active terms profile")
    if acknowledgement.terms_profile_id != profile.profile_id:
        raise ProviderUsagePolicyError("acknowledgement terms profile is not active")
    if acknowledgement.notice_version != profile.notice_version:
        raise ProviderUsagePolicyError("acknowledgement notice version is not active")
    if acknowledgement.operating_scope != profile.operating_scope:
        raise ProviderUsagePolicyError("acknowledgement operating scope mismatch")
    if acknowledgement.raw_evidence_policy_id != profile.raw_evidence_lifecycle.policy_id:
        raise ProviderUsagePolicyError("acknowledgement raw-evidence policy mismatch")
    if acknowledgement.declarations != profile.required_declarations:
        raise ProviderUsagePolicyError("required acknowledgement declarations are missing")
    if accepted_at < profile.reviewed_at_utc:
        raise ProviderUsagePolicyError("acknowledgement predates the active terms review")
    if accepted_at > evaluated_at:
        raise ProviderUsagePolicyError("acknowledgement acceptance time is in the future")
    expected_uid = build_provider_usage_acknowledgement_uid(acknowledgement)
    if acknowledgement.acknowledgement_uid != expected_uid:
        raise ProviderUsagePolicyError("acknowledgement identity mismatch")
    return ProviderUsageAuthorization(
        provider=provider,
        connection_uid=acknowledgement.connection_uid,
        acknowledgement_uid=acknowledgement.acknowledgement_uid,
        terms_profile_id=profile.profile_id,
        raw_evidence_lifecycle=profile.raw_evidence_lifecycle,
        provider_reported_entitlement_required=(
            profile.provider_reported_entitlement_required
        ),
    )


def authorize_raw_evidence_deletion(
    authorization: ProviderUsageAuthorization,
    *,
    approval_id: str,
    audit_recording_ready: bool,
    automatic: bool,
    authorized_at_utc: datetime,
) -> RawEvidenceDeletionAuthorization:
    """Authorize a future deletion operation without deleting any evidence."""

    lifecycle = authorization.raw_evidence_lifecycle
    if automatic or lifecycle.automatic_deletion_enabled:
        raise ProviderUsagePolicyError("automatic raw-evidence deletion is not approved")
    if not lifecycle.deletion_requires_explicit_approval:
        raise ProviderUsagePolicyError("raw-evidence lifecycle lacks an approval gate")
    approval = _require_safe_id(approval_id, field="approval_id")
    if not audit_recording_ready or not lifecycle.deletion_audit_required:
        raise ProviderUsagePolicyError("audited deletion evidence is required")
    authorized_at = _require_utc(authorized_at_utc, field="authorized_at_utc")
    payload = {
        "provider": authorization.provider,
        "connection_uid": authorization.connection_uid,
        "acknowledgement_uid": authorization.acknowledgement_uid,
        "raw_evidence_policy_id": lifecycle.policy_id,
        "approval_id": approval,
        "authorized_at_utc": authorized_at.isoformat().replace("+00:00", "Z"),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RawEvidenceDeletionAuthorization(
        deletion_authorization_uid=f"raw-evidence-deletion:{digest}",
        provider=authorization.provider,
        connection_uid=authorization.connection_uid,
        acknowledgement_uid=authorization.acknowledgement_uid,
        raw_evidence_policy_id=lifecycle.policy_id,
        approval_id=approval,
        authorized_at_utc=authorized_at,
    )
