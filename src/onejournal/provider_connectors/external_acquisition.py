"""Credential-free intake for exact externally acquired provider evidence.

The boundary accepts canonical manifest bytes, exact response bytes, and an
already established provider-use acknowledgement.  It has no filesystem,
network, credential, database, account, or order capability.  Provider bytes
remain authoritative source evidence; all normalized values are produced by
OneJournal adapters after the acquisition has been verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Literal, Mapping

from onejournal.brokers.schwab.positions_json import (
    SchwabPositionAdapterError,
    SchwabPositionCaptureContext,
    SchwabPositionMapping,
    broker_position_snapshot_from_bytes,
)
from onejournal.brokers.schwab.market_hours_json import (
    load_market_hours_json_bytes,
    market_hours_from_payload,
)
from onejournal.brokers.schwab.market_hours_resolver import (
    SchwabCombinedScheduleEvidence,
    SchwabScheduleEvidence,
)
from onejournal.brokers.schwab.quotes_json import (
    SchwabQuoteRequest,
    load_quotes_json_bytes,
    normalized_quotes_from_payload,
)
from onejournal.market_data.capture_artifact import quote_capture_artifact_bytes
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
    request_scope_json,
    validate_quote_capture,
)
from onejournal.market_data.quotes import QuoteFreshnessPolicy
from onejournal.provider_connectors.private_capture import (
    PRIVATE_CAPTURE_MANIFEST_SCHEMA,
    PrivateRawCaptureManifest,
)
from onejournal.provider_connectors.usage_policy import (
    ProviderUsagePolicy,
    ProviderUsagePolicyError,
    load_provider_usage_acknowledgement_artifact_bytes,
)
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot


EXTERNAL_PROVIDER_ACQUISITION_SCHEMA = "onejournal.external-provider-acquisition.v1"
EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME = "acquisition-manifest.json"
SCHWAB_EXTERNAL_ACQUISITION_PROFILE = "schwab-read-only-quotes-and-market-hours.v1"
SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE = (
    "schwab-read-only-single-account-positions.v1"
)
SCHWAB_QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"
SCHWAB_MARKET_HOURS_URL = "https://api.schwabapi.com/marketdata/v1/markets"
SCHWAB_POSITION_ACCOUNT_URL_TEMPLATE = (
    "https://api.schwabapi.com/trader/v1/accounts/{accountHash}"
)
MAX_EXTERNAL_ACQUISITION_MANIFEST_BYTES = 256 * 1024
MAX_EXTERNAL_RESPONSE_BYTES = 4 * 1024 * 1024

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.json")
_PROVIDER_ACCOUNT_HASH = re.compile(r"[A-Za-z0-9._~-]{1,512}")
_SOURCE_ROLES = frozenset(
    {"producer", "provider_client_boundary", "runtime", "source_contract"}
)
_QUOTE_SCHEDULE_OPERATIONS = ("quote", "market_hours")
_POSITION_OPERATIONS = ("position",)
_SUPPORTED_PROFILES = frozenset(
    {
        SCHWAB_EXTERNAL_ACQUISITION_PROFILE,
        SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    }
)
_ROOT_FIELDS = {
    "schema",
    "profile",
    "provider",
    "connection_uid",
    "source_owner",
    "source_artifacts",
    "acquisition_run_uid",
    "acquisition_approval_id",
    "acknowledgement_uid",
    "acknowledgement_sha256",
    "provider_use",
    "operation_allowlist",
    "requests",
    "controls",
    "completed_at_utc",
    "final_status",
    "manifest_written_last",
}
_REQUEST_FIELDS = {
    "request_uid",
    "operation",
    "method",
    "url",
    "query",
    "approved_market_date",
    "requested_at_utc",
    "received_at_utc",
    "status_code",
    "content_type",
    "response_filename",
    "response_byte_count",
    "response_sha256",
    "attempt_count",
    "redirects_followed",
}
_POSITION_REQUEST_FIELDS = _REQUEST_FIELDS | {"provider_account_hash_sha256"}


class ExternalProviderAcquisitionError(ValueError):
    """Raised when external provider evidence is unsafe or incomplete."""


@dataclass(frozen=True)
class ExternalAcquisitionQueryParameter:
    name: str
    value: str


@dataclass(frozen=True)
class ExternalAcquisitionSourceOwner:
    source_system: str
    owner_uid: str
    owner_epoch_uid: str
    operating_identity_uid: str


@dataclass(frozen=True)
class ExternalAcquisitionSourceArtifact:
    role: Literal[
        "producer", "provider_client_boundary", "runtime", "source_contract"
    ]
    artifact_uid: str
    sha256: str


@dataclass(frozen=True)
class ExternalAcquisitionProviderUse:
    terms_profile_id: str
    notice_version: str
    operating_scope: str
    raw_evidence_policy_id: str


@dataclass(frozen=True)
class ExternalAcquisitionRequest:
    request_uid: str
    operation: Literal["quote", "market_hours", "position"]
    method: str
    url: str
    query: tuple[ExternalAcquisitionQueryParameter, ...]
    approved_market_date: date
    requested_at_utc: datetime
    received_at_utc: datetime
    status_code: int
    content_type: str
    response_filename: str
    response_byte_count: int
    response_sha256: str
    attempt_count: int
    redirects_followed: int
    provider_account_hash_sha256: str | None = None


@dataclass(frozen=True)
class ExternalAcquisitionControls:
    provider_get_count: int
    oauth_refresh_count: int
    refresh_approval_id: str | None
    account_endpoint_calls: int
    position_endpoint_calls: int
    transaction_endpoint_calls: int
    order_endpoint_calls: int
    database_writes: int
    request_body_count: int
    response_count: int


@dataclass(frozen=True)
class ExternalProviderAcquisitionManifest:
    schema: str
    profile: str
    provider: str
    connection_uid: str
    source_owner: ExternalAcquisitionSourceOwner
    source_artifacts: tuple[ExternalAcquisitionSourceArtifact, ...]
    acquisition_run_uid: str
    acquisition_approval_id: str
    acknowledgement_uid: str
    acknowledgement_sha256: str
    provider_use: ExternalAcquisitionProviderUse
    operation_allowlist: tuple[str, ...]
    requests: tuple[ExternalAcquisitionRequest, ...]
    controls: ExternalAcquisitionControls
    completed_at_utc: datetime
    final_status: str
    manifest_written_last: bool


@dataclass(frozen=True)
class VerifiedExternalProviderAcquisition:
    """Canonical manifest plus exact checksum-verified provider bytes."""

    manifest: ExternalProviderAcquisitionManifest
    manifest_sha256: str
    response_bytes: Mapping[str, bytes]


@dataclass(frozen=True)
class ExternalSchwabQuoteMapping:
    """OneJournal-owned identity mapping for one external quote request."""

    request_uid: str
    instrument: QuoteInstrumentRequest


@dataclass(frozen=True)
class ConvertedExternalQuoteCapture:
    """In-memory canonical private-capture material; nothing has been written."""

    external_manifest_sha256: str
    external_request_uid: str
    source: QuoteEvidenceSource
    raw_response_bytes: bytes
    capture: QuoteCaptureEnvelope
    private_manifest: PrivateRawCaptureManifest
    capture_artifact_bytes: bytes


@dataclass(frozen=True)
class ConvertedExternalPositionSnapshot:
    """Credential-free in-memory position result; nothing has been written."""

    external_manifest_sha256: str
    external_request_uid: str
    raw_response_bytes: bytes
    snapshot: BrokerPositionSnapshot


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ExternalProviderAcquisitionError(f"{field} must be an object")
    return value


def _fields(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ExternalProviderAcquisitionError(f"{field} fields do not match the contract")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ExternalProviderAcquisitionError(f"{field} must be a secret-safe opaque identifier")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ExternalProviderAcquisitionError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ExternalProviderAcquisitionError(f"{field} must be an integer >= {minimum}")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ExternalProviderAcquisitionError(f"{field} must be an ISO-8601 UTC instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExternalProviderAcquisitionError(
            f"{field} must be an ISO-8601 UTC instant"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise ExternalProviderAcquisitionError(f"{field} must be expressed in UTC")
    return parsed.astimezone(UTC)


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ExternalProviderAcquisitionError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExternalProviderAcquisitionError(f"{field} must be YYYY-MM-DD") from exc


def _filename(value: object, field: str) -> str:
    if not isinstance(value, str) or not _FILENAME.fullmatch(value):
        raise ExternalProviderAcquisitionError(f"{field} must be a safe JSON filename")
    path = PurePosixPath(value)
    if len(path.parts) != 1:
        raise ExternalProviderAcquisitionError(f"{field} must not contain a path")
    return value


def _parse_query(value: object, field: str) -> tuple[ExternalAcquisitionQueryParameter, ...]:
    if not isinstance(value, list) or not value:
        raise ExternalProviderAcquisitionError(f"{field} must be a non-empty ordered array")
    result: list[ExternalAcquisitionQueryParameter] = []
    for index, item in enumerate(value):
        row = _mapping(item, f"{field}[{index}]")
        _fields(row, {"name", "value"}, f"{field}[{index}]")
        name = row["name"]
        parameter_value = row["value"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z_]{0,31}", name):
            raise ExternalProviderAcquisitionError(f"{field}[{index}].name is invalid")
        if not isinstance(parameter_value, str) or not parameter_value or any(
            character in parameter_value for character in "\r\n\x00"
        ):
            raise ExternalProviderAcquisitionError(f"{field}[{index}].value is invalid")
        result.append(ExternalAcquisitionQueryParameter(name=name, value=parameter_value))
    return tuple(result)


def _parse_request(
    value: object,
    index: int,
    *,
    profile: str,
) -> ExternalAcquisitionRequest:
    field = f"requests[{index}]"
    row = _mapping(value, field)
    expected_fields = (
        _POSITION_REQUEST_FIELDS
        if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
        else _REQUEST_FIELDS
    )
    _fields(row, expected_fields, field)
    operation = row["operation"]
    allowed_operations = (
        _POSITION_OPERATIONS
        if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
        else _QUOTE_SCHEDULE_OPERATIONS
    )
    if operation not in allowed_operations:
        raise ExternalProviderAcquisitionError(f"{field}.operation is unsupported")
    requested_at = _utc(row["requested_at_utc"], f"{field}.requested_at_utc")
    received_at = _utc(row["received_at_utc"], f"{field}.received_at_utc")
    if received_at < requested_at:
        raise ExternalProviderAcquisitionError(f"{field} receipt precedes request")
    content_type = row["content_type"]
    if (
        not isinstance(content_type, str)
        or content_type.split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise ExternalProviderAcquisitionError(
            f"{field}.content_type must be application/json"
        )
    request = ExternalAcquisitionRequest(
        request_uid=_safe_id(row["request_uid"], f"{field}.request_uid"),
        operation=operation,
        method=row["method"] if isinstance(row["method"], str) else "",
        url=row["url"] if isinstance(row["url"], str) else "",
        query=_parse_query(row["query"], f"{field}.query"),
        approved_market_date=_date(row["approved_market_date"], f"{field}.approved_market_date"),
        requested_at_utc=requested_at,
        received_at_utc=received_at,
        status_code=_integer(row["status_code"], f"{field}.status_code", minimum=100),
        content_type=content_type,
        response_filename=_filename(row["response_filename"], f"{field}.response_filename"),
        response_byte_count=_integer(
            row["response_byte_count"],
            f"{field}.response_byte_count",
            minimum=1,
        ),
        response_sha256=_digest(row["response_sha256"], f"{field}.response_sha256"),
        attempt_count=_integer(row["attempt_count"], f"{field}.attempt_count", minimum=1),
        redirects_followed=_integer(row["redirects_followed"], f"{field}.redirects_followed"),
        provider_account_hash_sha256=(
            _digest(
                row["provider_account_hash_sha256"],
                f"{field}.provider_account_hash_sha256",
            )
            if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
            else None
        ),
    )
    _validate_schwab_request(request, field, profile=profile)
    return request


def _validate_schwab_request(
    request: ExternalAcquisitionRequest,
    field: str,
    *,
    profile: str,
) -> None:
    if request.method != "GET" or request.attempt_count != 1 or request.redirects_followed != 0:
        raise ExternalProviderAcquisitionError(f"{field} must be one redirect-free GET attempt")
    if request.status_code != 200:
        raise ExternalProviderAcquisitionError(f"{field} provider status must be exactly 200")
    query = tuple((item.name, item.value) for item in request.query)
    if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE:
        if (
            request.operation != "position"
            or request.url != SCHWAB_POSITION_ACCOUNT_URL_TEMPLATE
            or query != (("fields", "positions"),)
            or request.provider_account_hash_sha256 is None
        ):
            raise ExternalProviderAcquisitionError(
                f"{field} position endpoint scope is invalid"
            )
    elif request.operation == "quote":
        if request.url != SCHWAB_QUOTES_URL or len(query) != 2:
            raise ExternalProviderAcquisitionError(f"{field} quote endpoint scope is invalid")
        if query[0][0] != "symbols" or query[1] != ("fields", "quote,reference"):
            raise ExternalProviderAcquisitionError(f"{field} quote query scope is invalid")
        symbol = query[0][1]
        if not re.fullmatch(r"[^,\x00-\x1f\x7f]{1,64}", symbol):
            raise ExternalProviderAcquisitionError(f"{field} must request exactly one safe symbol")
    else:
        expected = (
            ("markets", "equity"),
            ("markets", "option"),
            ("date", request.approved_market_date.isoformat()),
        )
        if request.url != SCHWAB_MARKET_HOURS_URL or query != expected:
            raise ExternalProviderAcquisitionError(f"{field} market-hours query scope is invalid")


def _parse_manifest(document: object) -> ExternalProviderAcquisitionManifest:
    root = _mapping(document, "acquisition manifest")
    _fields(root, _ROOT_FIELDS, "acquisition manifest")
    if root["schema"] != EXTERNAL_PROVIDER_ACQUISITION_SCHEMA:
        raise ExternalProviderAcquisitionError("unsupported external acquisition schema")
    profile = root["profile"]
    if profile not in _SUPPORTED_PROFILES or root["provider"] != "schwab":
        raise ExternalProviderAcquisitionError("unsupported external acquisition profile")

    owner_row = _mapping(root["source_owner"], "source_owner")
    _fields(
        owner_row,
        {"source_system", "owner_uid", "owner_epoch_uid", "operating_identity_uid"},
        "source_owner",
    )
    source_system = owner_row["source_system"]
    if source_system != "onebot":
        raise ExternalProviderAcquisitionError("Schwab bridge source_system must be onebot")
    owner = ExternalAcquisitionSourceOwner(
        source_system=source_system,
        owner_uid=_safe_id(owner_row["owner_uid"], "source_owner.owner_uid"),
        owner_epoch_uid=_safe_id(owner_row["owner_epoch_uid"], "source_owner.owner_epoch_uid"),
        operating_identity_uid=_safe_id(
            owner_row["operating_identity_uid"],
            "source_owner.operating_identity_uid",
        ),
    )
    artifact_rows = root["source_artifacts"]
    if not isinstance(artifact_rows, list) or not artifact_rows:
        raise ExternalProviderAcquisitionError("source_artifacts must be non-empty")
    artifacts: list[ExternalAcquisitionSourceArtifact] = []
    roles: set[str] = set()
    artifact_uids: set[str] = set()
    for index, item in enumerate(artifact_rows):
        field = f"source_artifacts[{index}]"
        row = _mapping(item, field)
        _fields(row, {"role", "artifact_uid", "sha256"}, field)
        role = row["role"]
        if role not in _SOURCE_ROLES or role in roles:
            raise ExternalProviderAcquisitionError(f"{field}.role is unsupported or duplicate")
        artifact_uid = _safe_id(row["artifact_uid"], f"{field}.artifact_uid")
        if artifact_uid in artifact_uids:
            raise ExternalProviderAcquisitionError(f"{field}.artifact_uid is duplicate")
        roles.add(role)
        artifact_uids.add(artifact_uid)
        artifacts.append(
            ExternalAcquisitionSourceArtifact(
                role=role,
                artifact_uid=artifact_uid,
                sha256=_digest(row["sha256"], f"{field}.sha256"),
            )
        )
    if "producer" not in roles or "provider_client_boundary" not in roles:
        raise ExternalProviderAcquisitionError(
            "producer and provider-client source hashes are required"
        )

    use_row = _mapping(root["provider_use"], "provider_use")
    _fields(
        use_row,
        {"terms_profile_id", "notice_version", "operating_scope", "raw_evidence_policy_id"},
        "provider_use",
    )
    provider_use = ExternalAcquisitionProviderUse(
        terms_profile_id=_safe_id(use_row["terms_profile_id"], "provider_use.terms_profile_id"),
        notice_version=_safe_id(use_row["notice_version"], "provider_use.notice_version"),
        operating_scope=(
            use_row["operating_scope"]
            if isinstance(use_row["operating_scope"], str)
            else ""
        ),
        raw_evidence_policy_id=_safe_id(
            use_row["raw_evidence_policy_id"],
            "provider_use.raw_evidence_policy_id",
        ),
    )

    request_rows = root["requests"]
    if not isinstance(request_rows, list):
        raise ExternalProviderAcquisitionError("requests must be an array")
    if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE:
        if len(request_rows) != 1:
            raise ExternalProviderAcquisitionError(
                "position profile requires exactly one bounded GET"
            )
    elif not 2 <= len(request_rows) <= 5:
        raise ExternalProviderAcquisitionError(
            "requests must contain two through five bounded GETs"
        )
    requests = tuple(
        _parse_request(item, index, profile=profile)
        for index, item in enumerate(request_rows)
    )
    if len({item.request_uid for item in requests}) != len(requests):
        raise ExternalProviderAcquisitionError("request_uid values must be unique")
    if len({item.response_filename for item in requests}) != len(requests):
        raise ExternalProviderAcquisitionError("response filenames must be unique")
    if len({item.response_sha256 for item in requests}) != len(requests):
        raise ExternalProviderAcquisitionError("response digests must be unique")
    operations = (
        tuple(root["operation_allowlist"])
        if isinstance(root["operation_allowlist"], list)
        else ()
    )
    if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE:
        if operations != _POSITION_OPERATIONS or requests[0].operation != "position":
            raise ExternalProviderAcquisitionError(
                "operation allowlist must bind only position"
            )
    else:
        if operations != _QUOTE_SCHEDULE_OPERATIONS or set(
            item.operation for item in requests
        ) != set(_QUOTE_SCHEDULE_OPERATIONS):
            raise ExternalProviderAcquisitionError(
                "operation allowlist must bind quote and market_hours"
            )
        quote_requests = tuple(item for item in requests if item.operation == "quote")
        schedule_requests = tuple(
            item for item in requests if item.operation == "market_hours"
        )
        if not 1 <= len(quote_requests) <= 2 or not 1 <= len(schedule_requests) <= 3:
            raise ExternalProviderAcquisitionError(
                "Schwab scope requires one or two quotes and one through three schedules"
            )
        if len({item.query[0].value.upper() for item in quote_requests}) != len(
            quote_requests
        ):
            raise ExternalProviderAcquisitionError("quote provider symbols must be unique")
        if len({item.approved_market_date for item in schedule_requests}) != len(
            schedule_requests
        ):
            raise ExternalProviderAcquisitionError("market-hours dates must be unique")

    controls_row = _mapping(root["controls"], "controls")
    _fields(
        controls_row,
        {
            "provider_get_count", "oauth_refresh_count", "refresh_approval_id",
            "account_endpoint_calls", "position_endpoint_calls", "transaction_endpoint_calls",
            "order_endpoint_calls", "database_writes", "request_body_count", "response_count",
        },
        "controls",
    )
    refresh_count = _integer(controls_row["oauth_refresh_count"], "controls.oauth_refresh_count")
    refresh_approval = controls_row["refresh_approval_id"]
    if refresh_count not in {0, 1}:
        raise ExternalProviderAcquisitionError(
            "oauth_refresh_count cannot exceed one approved owner action"
        )
    if (refresh_count == 0 and refresh_approval is not None) or (
        refresh_count == 1 and not isinstance(refresh_approval, str)
    ):
        raise ExternalProviderAcquisitionError("refresh approval does not match refresh count")
    checked_refresh_approval = (
        None
        if refresh_approval is None
        else _safe_id(refresh_approval, "controls.refresh_approval_id")
    )
    controls = ExternalAcquisitionControls(
        provider_get_count=_integer(
            controls_row["provider_get_count"], "controls.provider_get_count"
        ),
        oauth_refresh_count=refresh_count,
        refresh_approval_id=checked_refresh_approval,
        account_endpoint_calls=_integer(
            controls_row["account_endpoint_calls"],
            "controls.account_endpoint_calls",
        ),
        position_endpoint_calls=_integer(
            controls_row["position_endpoint_calls"],
            "controls.position_endpoint_calls",
        ),
        transaction_endpoint_calls=_integer(
            controls_row["transaction_endpoint_calls"],
            "controls.transaction_endpoint_calls",
        ),
        order_endpoint_calls=_integer(
            controls_row["order_endpoint_calls"],
            "controls.order_endpoint_calls",
        ),
        database_writes=_integer(controls_row["database_writes"], "controls.database_writes"),
        request_body_count=_integer(
            controls_row["request_body_count"], "controls.request_body_count"
        ),
        response_count=_integer(controls_row["response_count"], "controls.response_count"),
    )
    if controls.provider_get_count != len(requests) or controls.response_count != len(requests):
        raise ExternalProviderAcquisitionError(
            "provider GET and response counts must match requests"
        )
    permitted_position_count = (
        1 if profile == SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE else 0
    )
    if (
        controls.account_endpoint_calls != 0
        or controls.position_endpoint_calls != permitted_position_count
        or controls.transaction_endpoint_calls != 0
        or controls.order_endpoint_calls != 0
        or controls.database_writes != 0
        or controls.request_body_count != 0
    ):
        raise ExternalProviderAcquisitionError(
            "forbidden account, order, body, or database activity recorded"
        )

    completed_at = _utc(root["completed_at_utc"], "completed_at_utc")
    if completed_at < max(item.received_at_utc for item in requests):
        raise ExternalProviderAcquisitionError("completion precedes a provider response")
    if root["final_status"] != "complete" or root["manifest_written_last"] is not True:
        raise ExternalProviderAcquisitionError("acquisition is incomplete or not manifest-last")
    return ExternalProviderAcquisitionManifest(
        schema=EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
        profile=profile,
        provider="schwab",
        connection_uid=_safe_id(root["connection_uid"], "connection_uid"),
        source_owner=owner,
        source_artifacts=tuple(artifacts),
        acquisition_run_uid=_safe_id(root["acquisition_run_uid"], "acquisition_run_uid"),
        acquisition_approval_id=_safe_id(
            root["acquisition_approval_id"], "acquisition_approval_id"
        ),
        acknowledgement_uid=_safe_id(root["acknowledgement_uid"], "acknowledgement_uid"),
        acknowledgement_sha256=_digest(root["acknowledgement_sha256"], "acknowledgement_sha256"),
        provider_use=provider_use,
        operation_allowlist=operations,
        requests=requests,
        controls=controls,
        completed_at_utc=completed_at,
        final_status="complete",
        manifest_written_last=True,
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExternalProviderAcquisitionError("manifest timestamp must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _manifest_document(manifest: ExternalProviderAcquisitionManifest) -> dict[str, object]:
    return {
        "schema": manifest.schema,
        "profile": manifest.profile,
        "provider": manifest.provider,
        "connection_uid": manifest.connection_uid,
        "source_owner": {
            "source_system": manifest.source_owner.source_system,
            "owner_uid": manifest.source_owner.owner_uid,
            "owner_epoch_uid": manifest.source_owner.owner_epoch_uid,
            "operating_identity_uid": manifest.source_owner.operating_identity_uid,
        },
        "source_artifacts": [
            {"role": item.role, "artifact_uid": item.artifact_uid, "sha256": item.sha256}
            for item in manifest.source_artifacts
        ],
        "acquisition_run_uid": manifest.acquisition_run_uid,
        "acquisition_approval_id": manifest.acquisition_approval_id,
        "acknowledgement_uid": manifest.acknowledgement_uid,
        "acknowledgement_sha256": manifest.acknowledgement_sha256,
        "provider_use": {
            "terms_profile_id": manifest.provider_use.terms_profile_id,
            "notice_version": manifest.provider_use.notice_version,
            "operating_scope": manifest.provider_use.operating_scope,
            "raw_evidence_policy_id": manifest.provider_use.raw_evidence_policy_id,
        },
        "operation_allowlist": list(manifest.operation_allowlist),
        "requests": [
            {
                "request_uid": item.request_uid,
                "operation": item.operation,
                "method": item.method,
                "url": item.url,
                "query": [{"name": value.name, "value": value.value} for value in item.query],
                "approved_market_date": item.approved_market_date.isoformat(),
                "requested_at_utc": _timestamp(item.requested_at_utc),
                "received_at_utc": _timestamp(item.received_at_utc),
                "status_code": item.status_code,
                "content_type": item.content_type,
                "response_filename": item.response_filename,
                "response_byte_count": item.response_byte_count,
                "response_sha256": item.response_sha256,
                "attempt_count": item.attempt_count,
                "redirects_followed": item.redirects_followed,
                **(
                    {
                        "provider_account_hash_sha256": (
                            item.provider_account_hash_sha256
                        )
                    }
                    if item.operation == "position"
                    else {}
                ),
            }
            for item in manifest.requests
        ],
        "controls": {
            "provider_get_count": manifest.controls.provider_get_count,
            "oauth_refresh_count": manifest.controls.oauth_refresh_count,
            "refresh_approval_id": manifest.controls.refresh_approval_id,
            "account_endpoint_calls": manifest.controls.account_endpoint_calls,
            "position_endpoint_calls": manifest.controls.position_endpoint_calls,
            "transaction_endpoint_calls": manifest.controls.transaction_endpoint_calls,
            "order_endpoint_calls": manifest.controls.order_endpoint_calls,
            "database_writes": manifest.controls.database_writes,
            "request_body_count": manifest.controls.request_body_count,
            "response_count": manifest.controls.response_count,
        },
        "completed_at_utc": _timestamp(manifest.completed_at_utc),
        "final_status": manifest.final_status,
        "manifest_written_last": manifest.manifest_written_last,
    }


def external_provider_acquisition_manifest_bytes(
    manifest: ExternalProviderAcquisitionManifest,
) -> bytes:
    """Serialize a canonical acquisition manifest for deterministic replay."""

    document = _manifest_document(manifest)
    parsed = _parse_manifest(document)
    if parsed != manifest:
        raise ExternalProviderAcquisitionError("manifest object is not canonical")
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def load_external_provider_acquisition(
    manifest_bytes: bytes,
    *,
    response_bytes: Mapping[str, bytes],
    acknowledgement_bytes: bytes,
    usage_policy: ProviderUsagePolicy,
    evaluated_at_utc: datetime,
    expected_acquisition_run_uid: str,
    expected_acquisition_approval_id: str,
    expected_owner_uid: str,
    expected_owner_epoch_uid: str,
) -> VerifiedExternalProviderAcquisition:
    """Verify a complete canonical external bundle without reading or writing files."""

    if not isinstance(manifest_bytes, bytes) or not (
        0 < len(manifest_bytes) <= MAX_EXTERNAL_ACQUISITION_MANIFEST_BYTES
    ):
        raise ExternalProviderAcquisitionError("acquisition manifest byte size is invalid")
    try:
        document = json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExternalProviderAcquisitionError("acquisition manifest is not finite JSON") from exc
    manifest = _parse_manifest(document)
    if manifest_bytes != external_provider_acquisition_manifest_bytes(manifest):
        raise ExternalProviderAcquisitionError("acquisition manifest bytes are not canonical")
    if manifest.acquisition_run_uid != _safe_id(
        expected_acquisition_run_uid, "expected_acquisition_run_uid"
    ):
        raise ExternalProviderAcquisitionError("acquisition run identity mismatch")
    if manifest.acquisition_approval_id != _safe_id(
        expected_acquisition_approval_id, "expected_acquisition_approval_id"
    ):
        raise ExternalProviderAcquisitionError("acquisition approval mismatch")
    if manifest.source_owner.owner_uid != _safe_id(expected_owner_uid, "expected_owner_uid"):
        raise ExternalProviderAcquisitionError("source owner identity mismatch")
    if manifest.source_owner.owner_epoch_uid != _safe_id(
        expected_owner_epoch_uid, "expected_owner_epoch_uid"
    ):
        raise ExternalProviderAcquisitionError("source owner epoch mismatch")
    evaluated = evaluated_at_utc.astimezone(UTC) if evaluated_at_utc.tzinfo is not None else None
    if evaluated is None or evaluated_at_utc.utcoffset() is None:
        raise ExternalProviderAcquisitionError("evaluated_at_utc must include a timezone")
    if evaluated < manifest.completed_at_utc:
        raise ExternalProviderAcquisitionError("evaluation precedes acquisition completion")
    try:
        artifact, authorization = load_provider_usage_acknowledgement_artifact_bytes(
            acknowledgement_bytes,
            policy=usage_policy,
            expected_provider=manifest.provider,
            expected_connection_uid=manifest.connection_uid,
            evaluated_at_utc=evaluated,
            expected_sha256=manifest.acknowledgement_sha256,
        )
    except ProviderUsagePolicyError as exc:
        raise ExternalProviderAcquisitionError(
            "provider-use acknowledgement is not authorized"
        ) from exc
    if artifact.acknowledgement.acknowledgement_uid != manifest.acknowledgement_uid:
        raise ExternalProviderAcquisitionError("acknowledgement identity mismatch")
    profile = usage_policy.active_profiles[manifest.provider]
    if (
        manifest.provider_use.terms_profile_id != authorization.terms_profile_id
        or manifest.provider_use.notice_version != profile.notice_version
        or manifest.provider_use.operating_scope != profile.operating_scope
        or manifest.provider_use.raw_evidence_policy_id
        != authorization.raw_evidence_lifecycle.policy_id
    ):
        raise ExternalProviderAcquisitionError("provider-use profile lineage mismatch")

    expected_names = {item.response_filename for item in manifest.requests}
    if set(response_bytes) != expected_names:
        raise ExternalProviderAcquisitionError("response file set does not match the manifest")
    checked: dict[str, bytes] = {}
    for request in manifest.requests:
        body = response_bytes[request.response_filename]
        if not isinstance(body, bytes) or not 0 < len(body) <= MAX_EXTERNAL_RESPONSE_BYTES:
            raise ExternalProviderAcquisitionError("provider response byte size is invalid")
        if (
            len(body) != request.response_byte_count
            or sha256(body).hexdigest() != request.response_sha256
        ):
            raise ExternalProviderAcquisitionError(
                "provider response checksum or byte count mismatch"
            )
        checked[request.response_filename] = body
    return VerifiedExternalProviderAcquisition(
        manifest=manifest,
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
        response_bytes=MappingProxyType(checked),
    )


def _quote_run_uid(manifest_sha256: str, request: ExternalAcquisitionRequest) -> str:
    identity = sha256(
        f"{manifest_sha256}:{request.request_uid}:{request.response_sha256}".encode("ascii")
    ).hexdigest()
    return f"external-acquisition:{identity}"


def convert_external_schwab_quotes(
    acquisition: VerifiedExternalProviderAcquisition,
    *,
    mappings: tuple[ExternalSchwabQuoteMapping, ...],
    evaluated_at_utc: datetime,
    freshness_policy: QuoteFreshnessPolicy,
) -> tuple[ConvertedExternalQuoteCapture, ...]:
    """Convert every exact quote response to existing capture contracts in memory."""

    evaluated = evaluated_at_utc.astimezone(UTC) if evaluated_at_utc.tzinfo is not None else None
    if evaluated is None or evaluated_at_utc.utcoffset() is None:
        raise ExternalProviderAcquisitionError("evaluated_at_utc must include a timezone")
    quote_requests = tuple(
        item for item in acquisition.manifest.requests if item.operation == "quote"
    )
    mapping_by_uid = {item.request_uid: item for item in mappings}
    if len(mapping_by_uid) != len(mappings) or set(mapping_by_uid) != {
        item.request_uid for item in quote_requests
    }:
        raise ExternalProviderAcquisitionError(
            "OneJournal quote mappings must exactly cover quote requests"
        )
    results: list[ConvertedExternalQuoteCapture] = []
    for request in quote_requests:
        mapping = mapping_by_uid[request.request_uid]
        symbol = request.query[0].value
        if mapping.instrument.provider_instrument_id != symbol:
            raise ExternalProviderAcquisitionError(
                "OneJournal mapping differs from the approved provider symbol"
            )
        raw_body = acquisition.response_bytes[request.response_filename]
        raw_digest = request.response_sha256
        quote_run_uid = _quote_run_uid(acquisition.manifest_sha256, request)
        source = QuoteEvidenceSource(
            storage_kind="external_private_vault",
            locator=(
                f"schwab/{request.approved_market_date.isoformat()}/quote-captures/"
                f"{quote_run_uid}/quote-response.json"
            ),
            raw_sha256=raw_digest,
        )
        adapter_request = SchwabQuoteRequest(
            provider_symbol=mapping.instrument.provider_instrument_id,
            instrument_key=mapping.instrument.instrument_key,
            asset_class=mapping.instrument.asset_class,
            currency=mapping.instrument.currency,
        )
        quotes = normalized_quotes_from_payload(
            load_quotes_json_bytes(raw_body),
            requests=(adapter_request,),
            connection_uid=acquisition.manifest.connection_uid,
            asof=request.approved_market_date,
            received_at=request.received_at_utc,
            raw_path=(
                f"data/raw/schwab/external/{acquisition.manifest.acquisition_run_uid}/"
                f"{request.response_filename}"
            ),
            raw_sha256=raw_digest,
        )
        capture = QuoteCaptureEnvelope(
            quote_run_uid=quote_run_uid,
            provider="schwab",
            connection_uid=acquisition.manifest.connection_uid,
            asof=request.approved_market_date,
            started_at=request.requested_at_utc,
            received_at=request.received_at_utc,
            evaluated_at=evaluated,
            requests=(mapping.instrument,),
            source=source,
            adapter_version=quotes[0].adapter_version,
            quotes=quotes,
        )
        validate_quote_capture(capture, policy=freshness_policy)
        capture_bytes = quote_capture_artifact_bytes(capture)
        private_manifest = PrivateRawCaptureManifest(
            schema=PRIVATE_CAPTURE_MANIFEST_SCHEMA,
            provider="schwab",
            quote_run_uid=quote_run_uid,
            connection_uid=acquisition.manifest.connection_uid,
            approval_id=acquisition.manifest.acquisition_approval_id,
            acknowledgement_uid=acquisition.manifest.acknowledgement_uid,
            asof=request.approved_market_date,
            request_scope_sha256=sha256(request_scope_json(capture).encode("utf-8")).hexdigest(),
            started_at=request.requested_at_utc,
            received_at=request.received_at_utc,
            completed_at=evaluated,
            raw_sha256=raw_digest,
            raw_byte_count=len(raw_body),
            capture_envelope_sha256=sha256(capture_bytes).hexdigest(),
            final_status="captured_private_uningested",
        )
        results.append(
            ConvertedExternalQuoteCapture(
                external_manifest_sha256=acquisition.manifest_sha256,
                external_request_uid=request.request_uid,
                source=source,
                raw_response_bytes=raw_body,
                capture=capture,
                private_manifest=private_manifest,
                capture_artifact_bytes=capture_bytes,
            )
        )
    return tuple(results)


def convert_external_schwab_positions(
    acquisition: VerifiedExternalProviderAcquisition,
    *,
    provider_account_hash: str,
    provider_account_number: str,
    source_account_id: str,
    mappings: tuple[SchwabPositionMapping, ...],
) -> ConvertedExternalPositionSnapshot:
    """Convert one verified private position response without side effects.

    The raw provider account hash and account number are supplied only in
    memory by a later private operator.  The manifest carries only the hash
    digest and safe endpoint template, so neither identifier enters canonical
    acquisition metadata or ordinary audit output.
    """

    if (
        acquisition.manifest.profile
        != SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
    ):
        raise ExternalProviderAcquisitionError(
            "position conversion requires the position acquisition profile"
        )
    if not isinstance(provider_account_hash, str) or not _PROVIDER_ACCOUNT_HASH.fullmatch(
        provider_account_hash
    ):
        raise ExternalProviderAcquisitionError("provider account hash is invalid")
    source_account = _safe_id(source_account_id, "source_account_id")
    (request,) = acquisition.manifest.requests
    observed_account_hash_digest = sha256(provider_account_hash.encode("utf-8")).hexdigest()
    if observed_account_hash_digest != request.provider_account_hash_sha256:
        raise ExternalProviderAcquisitionError("provider account hash binding failed")
    raw_body = acquisition.response_bytes[request.response_filename]
    raw_path = (
        f"data/raw/schwab/external/{acquisition.manifest.acquisition_run_uid}/"
        f"{request.response_filename}"
    )
    try:
        snapshot = broker_position_snapshot_from_bytes(
            raw_body,
            context=SchwabPositionCaptureContext(
                request_url=(
                    "https://api.schwabapi.com/trader/v1/accounts/"
                    f"{provider_account_hash}?fields=positions"
                ),
                provider_account_hash_sha256=observed_account_hash_digest,
                provider_account_number=provider_account_number,
                connection_uid=acquisition.manifest.connection_uid,
                source_account_id=source_account,
                asof=request.approved_market_date,
                retrieved_at=request.received_at_utc,
                raw_path=raw_path,
                raw_sha256=request.response_sha256,
                method=request.method,
                status_code=request.status_code,
                content_type=request.content_type,
                attempt_count=request.attempt_count,
                redirect_count=request.redirects_followed,
            ),
            mappings=mappings,
        )
    except SchwabPositionAdapterError as exc:
        raise ExternalProviderAcquisitionError(
            "Schwab position evidence failed the OneJournal adapter contract"
        ) from exc
    return ConvertedExternalPositionSnapshot(
        external_manifest_sha256=acquisition.manifest_sha256,
        external_request_uid=request.request_uid,
        raw_response_bytes=raw_body,
        snapshot=snapshot,
    )


def build_external_schwab_schedule_evidence(
    acquisition: VerifiedExternalProviderAcquisition,
    *,
    normal_reference_date: date,
    valid_until_utc: datetime,
) -> SchwabCombinedScheduleEvidence:
    """Parse exact schedule members and bind them to the acquisition manifest."""

    if valid_until_utc.tzinfo is None or valid_until_utc.utcoffset() is None:
        raise ExternalProviderAcquisitionError("valid_until_utc must include a timezone")
    valid_until = valid_until_utc.astimezone(UTC)
    schedules: list[SchwabScheduleEvidence] = []
    for request in acquisition.manifest.requests:
        if request.operation != "market_hours":
            continue
        if valid_until <= request.received_at_utc:
            raise ExternalProviderAcquisitionError("schedule validity must follow retrieval")
        response = market_hours_from_payload(
            load_market_hours_json_bytes(acquisition.response_bytes[request.response_filename]),
            expected_date=request.approved_market_date,
        )
        schedules.append(
            SchwabScheduleEvidence(
                response=response,
                raw_path=(
                    f"data/raw/schwab/external/{acquisition.manifest.acquisition_run_uid}/"
                    f"{request.response_filename}"
                ),
                raw_sha256=request.response_sha256,
                retrieved_at=request.received_at_utc,
                valid_until=valid_until,
            )
        )
    if normal_reference_date not in {item.response.market_date for item in schedules}:
        raise ExternalProviderAcquisitionError(
            "normal reference date is absent from schedule evidence"
        )
    return SchwabCombinedScheduleEvidence(
        normal_reference_date=normal_reference_date,
        schedules=tuple(schedules),
        manifest_raw_path=(
            f"data/raw/schwab/external/{acquisition.manifest.acquisition_run_uid}/"
            f"{EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME}"
        ),
        manifest_raw_sha256=acquisition.manifest_sha256,
        manifest_member_sha256s=tuple(
            item.response_sha256 for item in acquisition.manifest.requests
        ),
        provider_source_version="Schwab Market Data Production 1.0.0",
    )
