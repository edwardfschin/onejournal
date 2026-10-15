"""Private, exact-package authority for a manually supplied refresh capture.

The browser supplies only the capture bytes. The operator-selected authorization
file and provider-use acknowledgement remain outside the website and Git.
This module verifies evidence in memory; it cannot contact a broker or write a
journal, request store, or release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping

from onejournal.local_web import private_file
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
    MAX_EXTERNAL_ACQUISITION_MANIFEST_BYTES,
    MAX_EXTERNAL_RESPONSE_BYTES,
    SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
    SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    VerifiedExternalProviderAcquisition,
    load_external_provider_acquisition,
)
from onejournal.provider_connectors.usage_policy import ProviderUsagePolicy


AUTHORIZATION_VERSION = "onejournal.manual-refresh-capture-authorization.v1"
MAX_AUTHORIZATION_BYTES = 16 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({
    "contract_version", "capture_scope", "manifest_sha256",
    "acquisition_run_uid", "acquisition_approval_id", "owner_uid",
    "owner_epoch_uid",
})
_PROFILES = {
    "current_positions": SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    "activity": SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
}


class ManualRefreshAuthorizationError(ValueError):
    """The selected private approval does not authorize this exact capture."""


@dataclass(frozen=True)
class ManualRefreshCaptureAuthorization:
    capture_scope: str
    manifest_sha256: str
    acquisition_run_uid: str
    acquisition_approval_id: str
    owner_uid: str
    owner_epoch_uid: str


def load_private_capture_authorization(
    path: Path, *, project_root: Path
) -> ManualRefreshCaptureAuthorization:
    """Load only a Mac-selected owner-private record, never an uploaded record."""

    try:
        if path.resolve().is_relative_to(project_root.resolve()):
            raise ManualRefreshAuthorizationError(
                "Refresh authorization must be outside the project checkout."
            )
        checked = private_file(path, "refresh authorization", private_parent=True)
        with checked.open("rb") as stream:
            body = stream.read(MAX_AUTHORIZATION_BYTES + 1)
        if not 0 < len(body) <= MAX_AUTHORIZATION_BYTES:
            raise ValueError
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise ValueError
        if document["contract_version"] != AUTHORIZATION_VERSION:
            raise ValueError
        scope = document["capture_scope"]
        digest = document["manifest_sha256"]
        if not isinstance(scope, str) or scope not in _PROFILES:
            raise ValueError
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ValueError
        for key in ("acquisition_run_uid", "acquisition_approval_id", "owner_uid", "owner_epoch_uid"):
            value = document[key]
            if not isinstance(value, str) or _ID.fullmatch(value) is None:
                raise ValueError
    except ManualRefreshAuthorizationError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise ManualRefreshAuthorizationError(
            "Private refresh authorization is missing or invalid."
        ) from exc
    return ManualRefreshCaptureAuthorization(
        capture_scope=scope,
        manifest_sha256=digest,
        acquisition_run_uid=document["acquisition_run_uid"],
        acquisition_approval_id=document["acquisition_approval_id"],
        owner_uid=document["owner_uid"],
        owner_epoch_uid=document["owner_epoch_uid"],
    )


def verify_authorized_capture(
    files: Mapping[str, bytes], *,
    authorization: ManualRefreshCaptureAuthorization,
    acknowledgement_bytes: bytes,
    usage_policy: ProviderUsagePolicy,
    evaluated_at_utc: datetime,
) -> VerifiedExternalProviderAcquisition:
    """Verify an uploaded package against independent private authority."""

    manifest = files.get(EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME)
    if not isinstance(manifest, bytes) or not 0 < len(manifest) <= MAX_EXTERNAL_ACQUISITION_MANIFEST_BYTES:
        raise ManualRefreshAuthorizationError("Capture manifest is missing or oversized.")
    if sha256(manifest).hexdigest() != authorization.manifest_sha256:
        raise ManualRefreshAuthorizationError("Capture differs from the private authorization.")
    responses = {
        name: body for name, body in files.items()
        if name != EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME
    }
    if len(responses) != (1 if authorization.capture_scope == "current_positions" else 2):
        raise ManualRefreshAuthorizationError("Capture file count differs from its scope.")
    if any(
        not isinstance(name, str) or Path(name).name != name
        or not isinstance(body, bytes) or not 0 < len(body) <= MAX_EXTERNAL_RESPONSE_BYTES
        for name, body in responses.items()
    ):
        raise ManualRefreshAuthorizationError("Capture response names or sizes are invalid.")
    try:
        acquisition = load_external_provider_acquisition(
            manifest,
            response_bytes=responses,
            acknowledgement_bytes=acknowledgement_bytes,
            usage_policy=usage_policy,
            evaluated_at_utc=evaluated_at_utc,
            expected_acquisition_run_uid=authorization.acquisition_run_uid,
            expected_acquisition_approval_id=authorization.acquisition_approval_id,
            expected_owner_uid=authorization.owner_uid,
            expected_owner_epoch_uid=authorization.owner_epoch_uid,
        )
    except ValueError as exc:
        raise ManualRefreshAuthorizationError("Capture validation failed.") from exc
    if acquisition.manifest.profile != _PROFILES[authorization.capture_scope]:
        raise ManualRefreshAuthorizationError("Capture type differs from the private authorization.")
    if acquisition.manifest.controls.oauth_refresh_count != 0:
        raise ManualRefreshAuthorizationError("Capture declares an unapproved token renewal.")
    return acquisition
