"""Provider-disabled macOS staging and Keychain credential boundaries.

The module contains no provider call, OAuth browser flow, journal database access,
listener, scheduler, or command-line entry point. Keychain and file-lock effects occur
only when an explicitly constructed runtime calls the corresponding methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from threading import Lock
from typing import Protocol

import yaml

from onejournal.provider_connectors.schwab_quotes import (
    ConnectorCredentialUse,
    ConnectorOwnerLease,
)


MACOS_STAGING_CONTRACT_VERSION = "onejournal.macos-provider-staging.v1"
MACOS_KEYCHAIN_CREDENTIAL_SCHEMA = "onejournal.macos-keychain-credential.v1"
MACOS_KEYCHAIN_SERVICE = "com.onejournal.provider-credentials"
MACOS_SECURITY_TOOL = "/usr/bin/security"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_REQUIRED_POLICY_FIELDS = {
    "contract_version",
    "target",
    "enabled",
    "credential_installation_enabled",
    "provider_calls_enabled",
    "token_refresh_enabled",
    "public_listener_enabled",
    "journal_database_mounted",
    "credential_backend",
    "private_capture_storage",
}
_REQUIRED_CREDENTIAL_FIELDS = {
    "schema",
    "provider",
    "connection_uid",
    "owner_epoch_uid",
    "generation_uid",
    "client_id",
    "client_secret",
    "access_token",
    "refresh_token",
    "access_token_expires_at_utc",
}


class MacOSStagingError(ValueError):
    """Raised when the local staging boundary cannot be proven."""


@dataclass(frozen=True)
class MacOSStagingPolicy:
    contract_version: str
    target: str
    enabled: bool
    credential_installation_enabled: bool
    provider_calls_enabled: bool
    token_refresh_enabled: bool
    public_listener_enabled: bool
    journal_database_mounted: bool
    credential_backend: str
    private_capture_storage: str


@dataclass(frozen=True, repr=False)
class MacOSKeychainCredentialRecord:
    """Secret-bearing record that must never be logged or serialized outside Keychain."""

    schema: str
    provider: str
    connection_uid: str
    owner_epoch_uid: str
    generation_uid: str
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    access_token_expires_at_utc: datetime

    def __repr__(self) -> str:
        return (
            "MacOSKeychainCredentialRecord(provider=<redacted>, "
            "connection_uid=<redacted>, secrets=<redacted>)"
        )


@dataclass(frozen=True)
class KeychainCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class KeychainCommandRunner(Protocol):
    def run(self, argv: tuple[str, ...], *, stdin: bytes | None) -> KeychainCommandResult:
        """Run only an exact Keychain command without logging arguments or streams."""


class SubprocessKeychainCommandRunner:
    """Production command runner; secrets are accepted on stdin, never argv."""

    def run(self, argv: tuple[str, ...], *, stdin: bytes | None) -> KeychainCommandResult:
        _validate_keychain_command(argv, stdin=stdin)
        try:
            completed = subprocess.run(
                argv,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MacOSStagingError("Keychain command failed") from exc
        return KeychainCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _validate_keychain_command(argv: tuple[str, ...], *, stdin: bytes | None) -> None:
    """Reject every Keychain operation outside this exact generic-password surface."""

    if len(argv) < 7 or argv[0] != MACOS_SECURITY_TOOL:
        raise MacOSStagingError("unsupported Keychain command")
    command = argv[1]
    if command not in {"find-generic-password", "add-generic-password"}:
        raise MacOSStagingError("unsupported Keychain command")
    if argv[-1] != "-w" or argv.count("-a") != 1 or argv.count("-s") != 1:
        raise MacOSStagingError("unsupported Keychain command")
    try:
        account = argv[argv.index("-a") + 1]
        service = argv[argv.index("-s") + 1]
    except (IndexError, ValueError) as exc:
        raise MacOSStagingError("unsupported Keychain command") from exc
    if not account.startswith("schwab:") or service != MACOS_KEYCHAIN_SERVICE:
        raise MacOSStagingError("unsupported Keychain command")
    _safe_id(account.removeprefix("schwab:"), "connection_uid")
    if command == "find-generic-password":
        expected = (
            MACOS_SECURITY_TOOL,
            command,
            "-a",
            account,
            "-s",
            MACOS_KEYCHAIN_SERVICE,
            "-w",
        )
        if argv != expected or stdin is not None:
            raise MacOSStagingError("unsupported Keychain command")
        return
    update = "-U" in argv
    expected = (
        MACOS_SECURITY_TOOL,
        command,
        *(("-U",) if update else ()),
        "-a",
        account,
        "-s",
        MACOS_KEYCHAIN_SERVICE,
        "-l",
        "OneJournal Schwab provider credential",
        "-D",
        "OneJournal provider credential",
        "-w",
    )
    if argv != expected or stdin is None:
        raise MacOSStagingError("unsupported Keychain command")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise MacOSStagingError(f"{field} must be a secret-safe opaque identifier")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MacOSStagingError(f"{field} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise MacOSStagingError(f"{field} must be expressed in UTC")
    return value.astimezone(UTC)


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise MacOSStagingError(f"{field} must be an ISO-8601 UTC instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacOSStagingError(f"{field} must be an ISO-8601 UTC instant") from exc
    return _utc(parsed, field)


def _secret(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 16_384
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        raise MacOSStagingError(f"{field} is unavailable or unsafe")
    return value


def load_macos_staging_policy(path: Path) -> MacOSStagingPolicy:
    """Load the exact provider-disabled local staging contract."""

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MacOSStagingError("unable to load macOS staging policy") from exc
    if not isinstance(document, dict) or not isinstance(document.get("marketdata"), dict):
        raise MacOSStagingError("market-data policy is unavailable")
    value = document["marketdata"].get("pnl02_t15_staging")
    if not isinstance(value, dict) or set(value) != _REQUIRED_POLICY_FIELDS:
        raise MacOSStagingError("macOS staging policy fields do not match the contract")
    if value["contract_version"] != MACOS_STAGING_CONTRACT_VERSION:
        raise MacOSStagingError("unsupported macOS staging contract")
    if value["target"] != "local_macos":
        raise MacOSStagingError("T15 staging target must be local_macos")
    for field in (
        "enabled",
        "credential_installation_enabled",
        "provider_calls_enabled",
        "token_refresh_enabled",
        "public_listener_enabled",
        "journal_database_mounted",
    ):
        if type(value[field]) is not bool:
            raise MacOSStagingError(f"{field} must be a boolean")
    if value["credential_backend"] != "macos_keychain":
        raise MacOSStagingError("credential backend must be macos_keychain")
    if value["private_capture_storage"] != "external_private_vault":
        raise MacOSStagingError("private capture storage must remain external")
    if value["public_listener_enabled"] or value["journal_database_mounted"]:
        raise MacOSStagingError("local staging isolation is weakened")
    for capability in (
        "credential_installation_enabled",
        "provider_calls_enabled",
        "token_refresh_enabled",
    ):
        if value[capability] and not value["enabled"]:
            raise MacOSStagingError(
                f"{capability.removesuffix('_enabled').replace('_', ' ')} cannot be "
                "enabled while staging is disabled"
            )
    return MacOSStagingPolicy(**value)


def macos_keychain_credential_record_bytes(
    record: MacOSKeychainCredentialRecord,
) -> bytes:
    """Return canonical secret bytes for direct Keychain stdin only."""

    _validate_record(record)
    payload = {
        "schema": record.schema,
        "provider": record.provider,
        "connection_uid": record.connection_uid,
        "owner_epoch_uid": record.owner_epoch_uid,
        "generation_uid": record.generation_uid,
        "client_id": record.client_id,
        "client_secret": record.client_secret,
        "access_token": record.access_token,
        "refresh_token": record.refresh_token,
        "access_token_expires_at_utc": _utc(
            record.access_token_expires_at_utc,
            "access_token_expires_at_utc",
        ).isoformat().replace("+00:00", "Z"),
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def load_macos_keychain_credential_record_bytes(
    body: bytes,
) -> MacOSKeychainCredentialRecord:
    """Parse exact Keychain bytes without exposing secret values in failures."""

    if not isinstance(body, bytes) or not body or len(body) > 65_536:
        raise MacOSStagingError("Keychain credential record is unavailable or unsafe")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacOSStagingError("Keychain credential record is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_CREDENTIAL_FIELDS:
        raise MacOSStagingError("Keychain credential fields do not match the contract")
    record = MacOSKeychainCredentialRecord(
        schema=payload["schema"],
        provider=payload["provider"],
        connection_uid=payload["connection_uid"],
        owner_epoch_uid=payload["owner_epoch_uid"],
        generation_uid=payload["generation_uid"],
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        access_token_expires_at_utc=_parse_utc(
            payload["access_token_expires_at_utc"],
            "access_token_expires_at_utc",
        ),
    )
    _validate_record(record)
    if macos_keychain_credential_record_bytes(record) != body:
        raise MacOSStagingError("Keychain credential record is not canonical")
    return record


def _validate_record(record: MacOSKeychainCredentialRecord) -> None:
    if not isinstance(record, MacOSKeychainCredentialRecord):
        raise MacOSStagingError("unsupported Keychain credential record")
    if record.schema != MACOS_KEYCHAIN_CREDENTIAL_SCHEMA:
        raise MacOSStagingError("unsupported Keychain credential schema")
    if record.provider != "schwab":
        raise MacOSStagingError("Keychain credential provider must be schwab")
    _safe_id(record.connection_uid, "connection_uid")
    _safe_id(record.owner_epoch_uid, "owner_epoch_uid")
    _safe_id(record.generation_uid, "generation_uid")
    _secret(record.client_id, "client_id")
    _secret(record.client_secret, "client_secret")
    _secret(record.access_token, "access_token")
    _secret(record.refresh_token, "refresh_token")
    _utc(record.access_token_expires_at_utc, "access_token_expires_at_utc")


class MacOSKeychainCredentialStore:
    """Opaque connector store backed by one non-exported generic-password item."""

    def __init__(
        self, *, runner: KeychainCommandRunner, policy: MacOSStagingPolicy
    ) -> None:
        self._runner = runner
        self._policy = policy

    def _require(self, capability: str) -> None:
        if not self._policy.enabled or not getattr(self._policy, capability):
            raise MacOSStagingError(f"{capability} is disabled by staging policy")

    @staticmethod
    def _account(connection_uid: str) -> str:
        return f"schwab:{_safe_id(connection_uid, 'connection_uid')}"

    def _load(self, connection_uid: str) -> MacOSKeychainCredentialRecord:
        result = self._runner.run(
            (
                MACOS_SECURITY_TOOL,
                "find-generic-password",
                "-a",
                self._account(connection_uid),
                "-s",
                MACOS_KEYCHAIN_SERVICE,
                "-w",
            ),
            stdin=None,
        )
        if result.returncode != 0:
            raise MacOSStagingError("Keychain credential is unavailable")
        return load_macos_keychain_credential_record_bytes(result.stdout)

    def checkout(
        self, *, provider: str, connection_uid: str, owner_lease: ConnectorOwnerLease
    ) -> ConnectorCredentialUse:
        if not self._policy.enabled:
            raise MacOSStagingError("macOS staging is disabled by policy")
        if provider != "schwab":
            raise MacOSStagingError("macOS staging accepts only provider=schwab")
        if (
            owner_lease.provider != provider
            or owner_lease.connection_uid != connection_uid
        ):
            raise MacOSStagingError("Keychain checkout lease mismatch")
        record = self._load(connection_uid)
        if record.owner_epoch_uid != owner_lease.owner_epoch_uid:
            raise MacOSStagingError("Keychain owner epoch mismatch")
        return ConnectorCredentialUse(
            provider="schwab",
            connection_uid=record.connection_uid,
            generation_uid=record.generation_uid,
        )

    def assert_current(self, credential_use: ConnectorCredentialUse) -> None:
        if not self._policy.enabled:
            raise MacOSStagingError("macOS staging is disabled by policy")
        record = self._load(credential_use.connection_uid)
        if (
            credential_use.provider != record.provider
            or credential_use.generation_uid != record.generation_uid
        ):
            raise MacOSStagingError("Keychain credential generation changed")

    def access_token(
        self,
        credential_use: ConnectorCredentialUse,
        *,
        evaluated_at_utc: datetime,
        minimum_validity_seconds: int = 300,
    ) -> str:
        """Return the access token only to an injected fixed Schwab transport."""

        self._require("provider_calls_enabled")
        if type(minimum_validity_seconds) is not int or minimum_validity_seconds < 0:
            raise MacOSStagingError("minimum_validity_seconds must not be negative")
        record = self._load(credential_use.connection_uid)
        if (
            credential_use.provider != record.provider
            or credential_use.generation_uid != record.generation_uid
        ):
            raise MacOSStagingError("Keychain credential generation changed")
        now = _utc(evaluated_at_utc, "evaluated_at_utc")
        if (record.access_token_expires_at_utc - now).total_seconds() < minimum_validity_seconds:
            raise MacOSStagingError("reauthentication_required")
        return record.access_token

    def install_new(
        self,
        *,
        owner_lease: ConnectorOwnerLease,
        record: MacOSKeychainCredentialRecord,
    ) -> None:
        """Create without overwrite; caller must hold the exact owner lease."""

        self._require("credential_installation_enabled")
        _validate_record(record)
        if (
            owner_lease.provider != record.provider
            or owner_lease.connection_uid != record.connection_uid
            or owner_lease.owner_epoch_uid != record.owner_epoch_uid
        ):
            raise MacOSStagingError("Keychain installation lease mismatch")
        body = macos_keychain_credential_record_bytes(record)
        result = self._runner.run(
            (
                MACOS_SECURITY_TOOL,
                "add-generic-password",
                "-a",
                self._account(record.connection_uid),
                "-s",
                MACOS_KEYCHAIN_SERVICE,
                "-l",
                "OneJournal Schwab provider credential",
                "-D",
                "OneJournal provider credential",
                "-w",
            ),
            stdin=body,
        )
        if result.returncode != 0:
            raise MacOSStagingError("Keychain credential installation failed")
        if macos_keychain_credential_record_bytes(self._load(record.connection_uid)) != body:
            raise MacOSStagingError("Keychain credential installation verification failed")

    def replace_generation(
        self,
        *,
        owner_lease: ConnectorOwnerLease,
        expected_generation_uid: str,
        record: MacOSKeychainCredentialRecord,
    ) -> None:
        """Generation-check and replace one Keychain record while the lease is held."""

        self._require("token_refresh_enabled")
        _validate_record(record)
        expected = _safe_id(expected_generation_uid, "expected_generation_uid")
        current = self._load(record.connection_uid)
        if (
            owner_lease.provider != record.provider
            or owner_lease.connection_uid != record.connection_uid
            or owner_lease.owner_epoch_uid != record.owner_epoch_uid
            or current.owner_epoch_uid != owner_lease.owner_epoch_uid
        ):
            raise MacOSStagingError("Keychain replacement lease mismatch")
        if current.generation_uid != expected or record.generation_uid == expected:
            raise MacOSStagingError("Keychain credential generation is stale")
        body = macos_keychain_credential_record_bytes(record)
        result = self._runner.run(
            (
                MACOS_SECURITY_TOOL,
                "add-generic-password",
                "-U",
                "-a",
                self._account(record.connection_uid),
                "-s",
                MACOS_KEYCHAIN_SERVICE,
                "-l",
                "OneJournal Schwab provider credential",
                "-D",
                "OneJournal provider credential",
                "-w",
            ),
            stdin=body,
        )
        if result.returncode != 0:
            raise MacOSStagingError("Keychain credential replacement failed")
        if macos_keychain_credential_record_bytes(self._load(record.connection_uid)) != body:
            raise MacOSStagingError("Keychain credential replacement verification failed")


class MacOSFileOwnerLeaseRegistry:
    """Cross-process owner lease using a private local advisory lock."""

    def __init__(self, *, lock_root: Path, owner_epoch_uid: str) -> None:
        self._lock_root = lock_root
        self._owner_epoch_uid = _safe_id(owner_epoch_uid, "owner_epoch_uid")
        self._active: dict[tuple[str, str], int] = {}
        self._guard = Lock()

    def _validate_root(self) -> None:
        try:
            metadata = self._lock_root.lstat()
        except OSError as exc:
            raise MacOSStagingError("owner lease root is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise MacOSStagingError("owner lease root must be a non-symlink 0700 directory")

    def acquire(self, *, provider: str, connection_uid: str) -> ConnectorOwnerLease:
        if provider != "schwab":
            raise MacOSStagingError("owner lease accepts only provider=schwab")
        connection = _safe_id(connection_uid, "connection_uid")
        self._validate_root()
        key = (provider, connection)
        lock_name = sha256(f"{provider}:{connection}".encode("utf-8")).hexdigest() + ".lock"
        lock_path = self._lock_root / lock_name
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            os.close(descriptor)
            raise MacOSStagingError("exclusive connector owner lease unavailable") from exc
        with self._guard:
            if key in self._active:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                raise MacOSStagingError("exclusive connector owner lease unavailable")
            self._active[key] = descriptor
        return ConnectorOwnerLease(
            provider=provider,
            connection_uid=connection,
            owner_epoch_uid=self._owner_epoch_uid,
        )

    def release(self, lease: ConnectorOwnerLease) -> None:
        key = (lease.provider, lease.connection_uid)
        with self._guard:
            descriptor = self._active.pop(key, None)
        if descriptor is None:
            raise MacOSStagingError("connector owner lease is not active")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
