"""Append-only private storage for provider-use acknowledgement artifacts.

This module has no credential, network, provider, database, overwrite, or delete
capability. A caller must supply an owner-approved declaration set and a
pre-existing 0700 private root. The store generates one opaque connection
identity and writes one canonical 0600 acknowledgement artifact exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable

from .usage_policy import (
    PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA,
    PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
    ProviderUsageAcknowledgement,
    ProviderUsageAcknowledgementArtifact,
    ProviderUsageAuthorization,
    ProviderUsagePolicy,
    ProviderUsagePolicyError,
    build_provider_usage_acknowledgement_uid,
    load_provider_usage_acknowledgement_artifact_bytes,
    provider_usage_acknowledgement_artifact_bytes,
    validate_provider_usage_acknowledgement,
)


_PROVIDER = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_CONNECTION_UID = re.compile(r"^connection:[a-z][a-z0-9_]{1,31}:[0-9a-f]{32}$")


class ProviderUsageAcknowledgementStoreError(ValueError):
    """Raised when a private acknowledgement cannot be stored or loaded safely."""


@dataclass(frozen=True)
class StoredProviderUsageAcknowledgement:
    path: Path
    sha256: str
    artifact: ProviderUsageAcknowledgementArtifact
    authorization: ProviderUsageAuthorization


def generate_provider_connection_uid(provider: str) -> str:
    """Generate a provider-scoped opaque identity with 128 random bits."""

    if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
        raise ProviderUsageAcknowledgementStoreError("provider is invalid")
    return f"connection:{provider}:{secrets.token_hex(16)}"


class LocalProviderUsageAcknowledgementStore:
    """Create and load canonical private acknowledgement artifacts without overwrite."""

    def __init__(
        self,
        *,
        private_root: Path,
        connection_uid_factory: Callable[[str], str] = generate_provider_connection_uid,
    ) -> None:
        self._root = private_root
        self._connection_uid_factory = connection_uid_factory

    def create(
        self,
        *,
        policy: ProviderUsagePolicy,
        provider: str,
        creation_approval_id: str,
        accepted_at_utc: datetime,
        evaluated_at_utc: datetime,
        product_version: str,
        declarations: frozenset[str],
    ) -> StoredProviderUsageAcknowledgement:
        """Write one owner-approved record; never infer or partially accept declarations."""

        self._require_root()
        if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
            raise ProviderUsageAcknowledgementStoreError("provider is invalid")
        profile = policy.active_profiles.get(provider)
        if profile is None:
            raise ProviderUsageAcknowledgementStoreError(
                "provider has no active terms profile"
            )
        if declarations != profile.required_declarations:
            raise ProviderUsageAcknowledgementStoreError(
                "complete owner-approved declarations are required"
            )
        connection_uid = self._connection_uid_factory(provider)
        if not isinstance(connection_uid, str) or not _CONNECTION_UID.fullmatch(
            connection_uid
        ):
            raise ProviderUsageAcknowledgementStoreError(
                "connection UID must contain an exact 128-bit opaque payload"
            )
        pending = ProviderUsageAcknowledgement(
            contract_version=PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
            acknowledgement_uid="pending",
            provider=provider,
            connection_uid=connection_uid,
            terms_profile_id=profile.profile_id,
            notice_version=profile.notice_version,
            operating_scope=profile.operating_scope,
            accepted_at_utc=accepted_at_utc,
            product_version=product_version,
            raw_evidence_policy_id=profile.raw_evidence_lifecycle.policy_id,
            declarations=declarations,
        )
        acknowledgement = replace(
            pending,
            acknowledgement_uid=build_provider_usage_acknowledgement_uid(pending),
        )
        try:
            authorization = validate_provider_usage_acknowledgement(
                acknowledgement,
                policy=policy,
                expected_provider=provider,
                expected_connection_uid=connection_uid,
                evaluated_at_utc=evaluated_at_utc,
            )
            body = provider_usage_acknowledgement_artifact_bytes(
                acknowledgement,
                creation_approval_id=creation_approval_id,
            )
        except ProviderUsagePolicyError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "provider acknowledgement is not authorized"
            ) from exc
        artifact_dir = (
            self._root
            / "provider-usage-acknowledgements"
            / provider
            / connection_uid
        )
        self._ensure_private_directories(artifact_dir)
        path = artifact_dir / f"{acknowledgement.acknowledgement_uid}.json"
        self._write_private_file(path, body)
        artifact, revalidated = load_provider_usage_acknowledgement_artifact_bytes(
            body,
            policy=policy,
            expected_provider=provider,
            expected_connection_uid=connection_uid,
            evaluated_at_utc=evaluated_at_utc,
            expected_sha256=sha256(body).hexdigest(),
        )
        if artifact.schema != PROVIDER_USAGE_ACKNOWLEDGEMENT_ARTIFACT_SCHEMA:
            raise ProviderUsageAcknowledgementStoreError(
                "stored acknowledgement schema changed"
            )
        return StoredProviderUsageAcknowledgement(
            path=path,
            sha256=sha256(body).hexdigest(),
            artifact=artifact,
            authorization=revalidated,
        )

    def load(
        self,
        *,
        path: Path,
        policy: ProviderUsagePolicy,
        expected_provider: str,
        expected_connection_uid: str,
        evaluated_at_utc: datetime,
        expected_sha256: str,
    ) -> StoredProviderUsageAcknowledgement:
        """Load one exact existing record without returning mutable storage access."""

        self._require_root()
        self._validate_private_file(path)
        body = path.read_bytes()
        try:
            artifact, authorization = load_provider_usage_acknowledgement_artifact_bytes(
                body,
                policy=policy,
                expected_provider=expected_provider,
                expected_connection_uid=expected_connection_uid,
                evaluated_at_utc=evaluated_at_utc,
                expected_sha256=expected_sha256,
            )
        except ProviderUsagePolicyError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "stored provider acknowledgement is invalid"
            ) from exc
        acknowledgement = artifact.acknowledgement
        canonical_path = (
            self._root
            / "provider-usage-acknowledgements"
            / acknowledgement.provider
            / acknowledgement.connection_uid
            / f"{acknowledgement.acknowledgement_uid}.json"
        )
        if path != canonical_path:
            raise ProviderUsageAcknowledgementStoreError(
                "stored provider acknowledgement is outside its canonical path"
            )
        return StoredProviderUsageAcknowledgement(
            path=path,
            sha256=sha256(body).hexdigest(),
            artifact=artifact,
            authorization=authorization,
        )

    def _require_root(self) -> None:
        if (
            not self._root.is_absolute()
            or self._root.is_symlink()
            or not self._root.is_dir()
        ):
            raise ProviderUsageAcknowledgementStoreError(
                "private acknowledgement root must be an absolute directory"
            )
        if self._root != self._root.resolve(strict=True):
            raise ProviderUsageAcknowledgementStoreError(
                "private acknowledgement root must not traverse symlinks"
            )
        if stat.S_IMODE(self._root.stat().st_mode) != 0o700:
            raise ProviderUsageAcknowledgementStoreError(
                "private acknowledgement root must have mode 0700"
            )

    def _ensure_private_directories(self, target: Path) -> None:
        relative = target.relative_to(self._root)
        current = self._root
        for component in relative.parts:
            current = current / component
            if current.exists() or current.is_symlink():
                if current.is_symlink() or not current.is_dir():
                    raise ProviderUsageAcknowledgementStoreError(
                        "private acknowledgement path is unsafe"
                    )
                if stat.S_IMODE(current.stat().st_mode) != 0o700:
                    raise ProviderUsageAcknowledgementStoreError(
                        "private acknowledgement directory must have mode 0700"
                    )
            else:
                current.mkdir(mode=0o700)

    def _validate_private_file(self, path: Path) -> None:
        if not path.is_absolute():
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact path must be absolute"
            )
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact path is unavailable"
            ) from exc
        if path != resolved:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact path must not traverse symlinks"
            )
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact escapes its private root"
            ) from exc
        current = self._root
        for component in relative.parts[:-1]:
            current = current / component
            if (
                current.is_symlink()
                or not current.is_dir()
                or stat.S_IMODE(current.stat().st_mode) != 0o700
            ):
                raise ProviderUsageAcknowledgementStoreError(
                    "private acknowledgement path is unsafe"
                )
        if path.is_symlink() or not path.is_file():
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact must be a regular non-symlink file"
            )
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact must have mode 0600"
            )

    @staticmethod
    def _write_private_file(path: Path, body: bytes) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact already exists; overwrite refused"
            ) from exc
        try:
            written = 0
            while written < len(body):
                count = os.write(descriptor, body[written:])
                if count <= 0:
                    raise OSError("acknowledgement artifact write was incomplete")
                written += count
            os.fsync(descriptor)
        except OSError as exc:
            raise ProviderUsageAcknowledgementStoreError(
                "acknowledgement artifact write failed"
            ) from exc
        finally:
            os.close(descriptor)
