"""Offline-only, read-only Schwab quote-connector boundary.

The module deliberately ships no HTTP client, real credential backend, database
dependency, scheduler, or command-line entry point. A later, separately approved
runtime supplies real credential and transport implementations. This boundary accepts
only an explicit quote request,
proves its current provider-use acknowledgement, serializes a local owner lease,
and turns exact response bytes from an injected test transport into the existing
provider-neutral capture envelope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import re
from threading import Lock
from typing import Protocol

from onejournal.brokers.schwab.quotes_json import (
    SchwabQuoteRequest,
    load_quotes_json_bytes,
    normalized_quotes_from_payload,
)
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
    validate_quote_capture,
)
from onejournal.market_data.quotes import QuoteFreshnessPolicy
from onejournal.provider_connectors.usage_policy import (
    ProviderUsageAcknowledgement,
    ProviderUsageAuthorization,
    ProviderUsagePolicy,
    ProviderUsagePolicyError,
    validate_provider_usage_acknowledgement,
)
from onejournal.provider_connectors.private_capture import (
    LocalPrivateRawCaptureStore,
    PrivateRawCaptureManifest,
)


SCHWAB_QUOTE_CONNECTOR_CONTRACT_VERSION = "onejournal.schwab.quote-connector.v1"
SCHWAB_QUOTE_OPERATION = "quote_capture"
SCHWAB_QUOTE_RETRY_POLICY_VERSION = "onejournal.schwab.quote-retry.v1"
SCHWAB_QUOTE_MAX_ATTEMPTS = 1
MAX_RESPONSE_BYTES = 1024 * 1024

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class SchwabQuoteConnectorError(ValueError):
    """Raised when an offline connector capture cannot be safely accepted."""


@dataclass(frozen=True)
class SchwabQuoteCaptureRequest:
    """The only request shape accepted by the Schwab quote connector."""

    quote_run_uid: str
    connection_uid: str
    approval_id: str
    asof: date
    started_at: datetime
    evaluated_at: datetime
    requests: tuple[QuoteInstrumentRequest, ...]
    acknowledgement: ProviderUsageAcknowledgement
    contract_version: str = SCHWAB_QUOTE_CONNECTOR_CONTRACT_VERSION


@dataclass(frozen=True)
class ConnectorCredentialUse:
    """Opaque, secret-free proof of the checked-out credential generation."""

    provider: str
    connection_uid: str
    generation_uid: str


@dataclass(frozen=True)
class ConnectorOwnerLease:
    """An exclusive, connection-scoped owner lease with no credential material."""

    provider: str
    connection_uid: str
    owner_epoch_uid: str


@dataclass(frozen=True)
class SchwabQuoteTransportRequest:
    """Fixed quote operation passed to an injected provider-specific transport."""

    provider: str
    connection_uid: str
    quote_run_uid: str
    provider_symbols: tuple[str, ...]
    operation: str = SCHWAB_QUOTE_OPERATION


@dataclass(frozen=True)
class SchwabQuoteTransportResponse:
    """Exact response bytes and safe metadata returned by an injected transport."""

    status_code: int
    content_type: str
    body: bytes
    received_at: datetime


@dataclass(frozen=True)
class SchwabQuoteCaptureAudit:
    """Secret-free success audit; exact request and response data are excluded."""

    contract_version: str
    quote_run_uid: str
    provider: str
    connection_uid: str
    operation: str
    approval_id: str
    acknowledgement_uid: str
    credential_generation_uid: str
    request_scope_sha256: str
    requested_instrument_count: int
    started_at: datetime
    received_at: datetime
    completed_at: datetime
    attempt_count: int
    raw_sha256: str
    raw_byte_count: int
    final_status: str


@dataclass(frozen=True)
class SchwabQuoteCaptureResult:
    """Private-captured evidence handoff for later approved journal ingestion."""

    capture: QuoteCaptureEnvelope
    raw_response_bytes: bytes
    audit: SchwabQuoteCaptureAudit
    authorization: ProviderUsageAuthorization


class CredentialStore(Protocol):
    """A provider-owned opaque credential capability; it never returns a secret."""

    def checkout(
        self, *, provider: str, connection_uid: str, owner_lease: ConnectorOwnerLease
    ) -> ConnectorCredentialUse:
        """Return the generation currently owned by the exclusive connector lease."""

    def assert_current(self, credential_use: ConnectorCredentialUse) -> None:
        """Fail if a credential generation changed during the provider operation."""


class ConnectorOwnerLeaseRegistry(Protocol):
    """Serializes one active connector owner for a provider connection."""

    def acquire(self, *, provider: str, connection_uid: str) -> ConnectorOwnerLease:
        """Acquire exclusive ownership or fail closed."""

    def release(self, lease: ConnectorOwnerLease) -> None:
        """Release only the exact current lease."""


class SchwabQuoteTransport(Protocol):
    """Provider-specific read-only transport with no arbitrary URL/body surface."""

    def fetch_quotes(
        self,
        *,
        request: SchwabQuoteTransportRequest,
        credential_use: ConnectorCredentialUse,
    ) -> SchwabQuoteTransportResponse:
        """Return one exact quote-response body for the fixed quote operation."""


class InMemoryConnectorOwnerLeaseRegistry:
    """Non-persistent test lease registry; not a deployment lease implementation."""

    def __init__(self, *, owner_epoch_uid: str = "offline-owner-epoch-0001") -> None:
        _safe_id(owner_epoch_uid, "owner_epoch_uid")
        self._owner_epoch_uid = owner_epoch_uid
        self._active: set[tuple[str, str]] = set()
        self._lock = Lock()

    def acquire(self, *, provider: str, connection_uid: str) -> ConnectorOwnerLease:
        key = (_provider(provider), _safe_id(connection_uid, "connection_uid"))
        with self._lock:
            if key in self._active:
                raise SchwabQuoteConnectorError("exclusive connector owner lease unavailable")
            self._active.add(key)
        return ConnectorOwnerLease(
            provider=key[0], connection_uid=key[1], owner_epoch_uid=self._owner_epoch_uid
        )

    def release(self, lease: ConnectorOwnerLease) -> None:
        key = (lease.provider, lease.connection_uid)
        with self._lock:
            if key not in self._active:
                raise SchwabQuoteConnectorError("connector owner lease is not active")
            self._active.remove(key)


class InMemoryCredentialStore:
    """Non-persistent fake credential store for offline tests; it stores no secret."""

    def __init__(self, *, generation_uid: str = "offline-credential-generation-0001") -> None:
        _safe_id(generation_uid, "generation_uid")
        self._generation_uid = generation_uid

    def checkout(
        self, *, provider: str, connection_uid: str, owner_lease: ConnectorOwnerLease
    ) -> ConnectorCredentialUse:
        checked_provider = _provider(provider)
        checked_connection = _safe_id(connection_uid, "connection_uid")
        if (
            owner_lease.provider != checked_provider
            or owner_lease.connection_uid != checked_connection
        ):
            raise SchwabQuoteConnectorError("credential checkout lease mismatch")
        return ConnectorCredentialUse(
            provider=checked_provider,
            connection_uid=checked_connection,
            generation_uid=self._generation_uid,
        )

    def rotate_for_test(self, *, generation_uid: str) -> None:
        """Simulate a newer owner generation without handling a real credential."""

        self._generation_uid = _safe_id(generation_uid, "generation_uid")

    def assert_current(self, credential_use: ConnectorCredentialUse) -> None:
        if credential_use.generation_uid != self._generation_uid:
            raise SchwabQuoteConnectorError("credential generation changed during capture")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise SchwabQuoteConnectorError(f"{field} must be a secret-safe opaque identifier")
    return value


def _provider(value: object) -> str:
    if value != "schwab":
        raise SchwabQuoteConnectorError("Schwab connector accepts only provider=schwab")
    return "schwab"


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabQuoteConnectorError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _request_scope_sha256(requests: tuple[QuoteInstrumentRequest, ...]) -> str:
    rows = sorted(
        (asdict(request) for request in requests),
        key=lambda row: (row["instrument_key"], row["provider_instrument_id"]),
    )
    return sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_request(request: SchwabQuoteCaptureRequest) -> None:
    if request.contract_version != SCHWAB_QUOTE_CONNECTOR_CONTRACT_VERSION:
        raise SchwabQuoteConnectorError("unsupported Schwab quote connector contract")
    _safe_id(request.quote_run_uid, "quote_run_uid")
    _safe_id(request.connection_uid, "connection_uid")
    _safe_id(request.approval_id, "approval_id")
    started_at = _utc(request.started_at, "started_at")
    evaluated_at = _utc(request.evaluated_at, "evaluated_at")
    if evaluated_at < started_at:
        raise SchwabQuoteConnectorError("evaluated_at must not precede started_at")
    if not request.requests:
        raise SchwabQuoteConnectorError("at least one exact quote request is required")
    keys: set[str] = set()
    provider_ids: set[str] = set()
    for item in request.requests:
        if item.instrument_key in keys or item.provider_instrument_id in provider_ids:
            raise SchwabQuoteConnectorError("quote request identities must be unique")
        keys.add(item.instrument_key)
        provider_ids.add(item.provider_instrument_id)
        SchwabQuoteRequest(
            provider_symbol=item.provider_instrument_id,
            instrument_key=item.instrument_key,
            asset_class=item.asset_class,
            currency=item.currency,
        )


def _raw_locator(request: SchwabQuoteCaptureRequest) -> str:
    return (
        f"data/raw/schwab/{request.asof.isoformat()}/quote-captures/"
        f"{request.quote_run_uid}/quote-response.json"
    )


class SchwabQuoteConnector:
    """Capture one complete Schwab quote batch through injected offline ports."""

    def __init__(
        self,
        *,
        usage_policy: ProviderUsagePolicy,
        freshness_policy: QuoteFreshnessPolicy,
        credential_store: CredentialStore,
        owner_leases: ConnectorOwnerLeaseRegistry,
        transport: SchwabQuoteTransport,
        private_capture_store: LocalPrivateRawCaptureStore,
    ) -> None:
        self._usage_policy = usage_policy
        self._freshness_policy = freshness_policy
        self._credential_store = credential_store
        self._owner_leases = owner_leases
        self._transport = transport
        self._private_capture_store = private_capture_store

    def capture(self, request: SchwabQuoteCaptureRequest) -> SchwabQuoteCaptureResult:
        """Commit a validated private capture or fail before journal persistence."""

        _validate_request(request)
        started_at = _utc(request.started_at, "started_at")
        evaluated_at = _utc(request.evaluated_at, "evaluated_at")
        try:
            authorization = validate_provider_usage_acknowledgement(
                request.acknowledgement,
                policy=self._usage_policy,
                expected_provider="schwab",
                expected_connection_uid=request.connection_uid,
                evaluated_at_utc=evaluated_at,
            )
        except ProviderUsagePolicyError as exc:
            raise SchwabQuoteConnectorError("provider usage authorization failed") from exc
        if not authorization.provider_reported_entitlement_required:
            raise SchwabQuoteConnectorError("provider entitlement evidence is required")

        lease = self._owner_leases.acquire(
            provider="schwab", connection_uid=request.connection_uid
        )
        try:
            credential_use = self._credential_store.checkout(
                provider="schwab",
                connection_uid=request.connection_uid,
                owner_lease=lease,
            )
            if (
                credential_use.provider != "schwab"
                or credential_use.connection_uid != request.connection_uid
            ):
                raise SchwabQuoteConnectorError("credential use does not bind this request")
            _safe_id(credential_use.generation_uid, "credential_generation_uid")
            transport_request = SchwabQuoteTransportRequest(
                provider="schwab",
                connection_uid=request.connection_uid,
                quote_run_uid=request.quote_run_uid,
                provider_symbols=tuple(item.provider_instrument_id for item in request.requests),
            )
            response = self._transport.fetch_quotes(
                request=transport_request, credential_use=credential_use
            )
            self._credential_store.assert_current(credential_use)
            result = self._capture_response(
                request=request,
                authorization=authorization,
                credential_use=credential_use,
                response=response,
                started_at=started_at,
                evaluated_at=evaluated_at,
            )
        finally:
            self._owner_leases.release(lease)
        return result

    def _capture_response(
        self,
        *,
        request: SchwabQuoteCaptureRequest,
        authorization: ProviderUsageAuthorization,
        credential_use: ConnectorCredentialUse,
        response: SchwabQuoteTransportResponse,
        started_at: datetime,
        evaluated_at: datetime,
    ) -> SchwabQuoteCaptureResult:
        if not isinstance(response, SchwabQuoteTransportResponse):
            raise SchwabQuoteConnectorError("transport returned an unsupported response")
        if response.status_code != 200:
            raise SchwabQuoteConnectorError("Schwab quote transport did not return HTTP 200")
        if not isinstance(response.content_type, str) or "application/json" not in response.content_type.lower():
            raise SchwabQuoteConnectorError("Schwab quote transport content type is unsafe")
        if not isinstance(response.body, bytes) or not response.body or len(response.body) > MAX_RESPONSE_BYTES:
            raise SchwabQuoteConnectorError("Schwab quote response byte size is unsafe")
        received_at = _utc(response.received_at, "received_at")
        if not started_at <= received_at <= evaluated_at:
            raise SchwabQuoteConnectorError("response timing is outside the requested capture")

        raw_sha256 = sha256(response.body).hexdigest()
        source = self._private_capture_store.source_for(
            provider="schwab",
            asof=request.asof,
            quote_run_uid=request.quote_run_uid,
            raw_sha256=raw_sha256,
        )
        payload = load_quotes_json_bytes(response.body)
        adapter_requests = tuple(
            SchwabQuoteRequest(
                provider_symbol=item.provider_instrument_id,
                instrument_key=item.instrument_key,
                asset_class=item.asset_class,
                currency=item.currency,
            )
            for item in request.requests
        )
        quotes = normalized_quotes_from_payload(
            payload,
            requests=adapter_requests,
            connection_uid=request.connection_uid,
            asof=request.asof,
            received_at=received_at,
            raw_path=_raw_locator(request),
            raw_sha256=raw_sha256,
        )
        capture = QuoteCaptureEnvelope(
            quote_run_uid=request.quote_run_uid,
            provider="schwab",
            connection_uid=request.connection_uid,
            asof=request.asof,
            started_at=started_at,
            received_at=received_at,
            evaluated_at=evaluated_at,
            requests=request.requests,
            source=source,
            adapter_version=quotes[0].adapter_version,
            quotes=quotes,
        )
        validate_quote_capture(capture, policy=self._freshness_policy)
        audit = SchwabQuoteCaptureAudit(
            contract_version=SCHWAB_QUOTE_CONNECTOR_CONTRACT_VERSION,
            quote_run_uid=request.quote_run_uid,
            provider="schwab",
            connection_uid=request.connection_uid,
            operation=SCHWAB_QUOTE_OPERATION,
            approval_id=request.approval_id,
            acknowledgement_uid=authorization.acknowledgement_uid,
            credential_generation_uid=credential_use.generation_uid,
            request_scope_sha256=_request_scope_sha256(request.requests),
            requested_instrument_count=len(request.requests),
            started_at=started_at,
            received_at=received_at,
            completed_at=evaluated_at,
            attempt_count=SCHWAB_QUOTE_MAX_ATTEMPTS,
            raw_sha256=raw_sha256,
            raw_byte_count=len(response.body),
            final_status="captured_private_uningested",
        )
        self._private_capture_store.commit(
            source=source,
            raw_response_bytes=response.body,
            manifest=PrivateRawCaptureManifest(
                schema="onejournal.private-raw-capture-manifest.v1",
                provider="schwab",
                quote_run_uid=request.quote_run_uid,
                connection_uid=request.connection_uid,
                approval_id=request.approval_id,
                acknowledgement_uid=authorization.acknowledgement_uid,
                asof=request.asof,
                request_scope_sha256=audit.request_scope_sha256,
                started_at=started_at,
                received_at=received_at,
                completed_at=evaluated_at,
                raw_sha256=raw_sha256,
                raw_byte_count=len(response.body),
                final_status="captured_private_uningested",
            ),
        )
        return SchwabQuoteCaptureResult(
            capture=capture,
            raw_response_bytes=response.body,
            audit=audit,
            authorization=authorization,
        )
