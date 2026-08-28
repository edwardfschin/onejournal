"""Local immutable private raw-capture storage for provider connectors.

This store accepts only exact bytes plus secret-free metadata. It has no provider,
credential, database, deletion, or overwrite capability. The operator must provision
the private root with mode 0700 before a connector can use it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Mapping
from uuid import uuid4

from onejournal.market_data.ingestion import QuoteEvidenceSource


PRIVATE_CAPTURE_MANIFEST_SCHEMA = "onejournal.private-raw-capture-manifest.v1"


class PrivateRawCaptureError(ValueError):
    """Raised when an immutable private raw capture cannot be safely stored."""


@dataclass(frozen=True)
class PrivateRawCaptureManifest:
    """Secret-free metadata stored beside exact private response bytes."""

    schema: str
    provider: str
    quote_run_uid: str
    connection_uid: str
    approval_id: str
    acknowledgement_uid: str
    asof: date
    request_scope_sha256: str
    started_at: datetime
    received_at: datetime
    completed_at: datetime
    raw_sha256: str
    raw_byte_count: int
    final_status: str


class LocalPrivateRawCaptureStore:
    """Atomically create one append-only private raw-capture directory."""

    def __init__(self, *, private_root: Path) -> None:
        self._root = private_root

    def source_for(
        self, *, provider: str, asof: date, quote_run_uid: str, raw_sha256: str
    ) -> QuoteEvidenceSource:
        self._require_root()
        if provider != "schwab":
            raise PrivateRawCaptureError("private capture provider is unsupported")
        if not isinstance(quote_run_uid, str) or not quote_run_uid:
            raise PrivateRawCaptureError("quote_run_uid is required")
        if not isinstance(raw_sha256, str) or len(raw_sha256) != 64:
            raise PrivateRawCaptureError("raw_sha256 is invalid")
        return QuoteEvidenceSource(
            storage_kind="external_private_vault",
            locator=(
                f"{provider}/{asof.isoformat()}/quote-captures/"
                f"{quote_run_uid}/quote-response.json"
            ),
            raw_sha256=raw_sha256,
        )

    def commit(
        self,
        *,
        source: QuoteEvidenceSource,
        raw_response_bytes: bytes,
        manifest: PrivateRawCaptureManifest,
    ) -> None:
        self._require_root()
        if source.storage_kind != "external_private_vault":
            raise PrivateRawCaptureError("private capture source kind is unsafe")
        if manifest.schema != PRIVATE_CAPTURE_MANIFEST_SCHEMA:
            raise PrivateRawCaptureError("private capture manifest schema is unsupported")
        if source.locator != (
            f"{manifest.provider}/{manifest.asof.isoformat()}"
            f"/quote-captures/{manifest.quote_run_uid}/quote-response.json"
        ):
            raise PrivateRawCaptureError("private capture locator does not bind the manifest")
        if not manifest.started_at <= manifest.received_at <= manifest.completed_at:
            raise PrivateRawCaptureError("private capture manifest timing is unsafe")
        if not isinstance(raw_response_bytes, bytes) or not raw_response_bytes:
            raise PrivateRawCaptureError("raw capture must be non-empty bytes")
        if len(raw_response_bytes) != manifest.raw_byte_count:
            raise PrivateRawCaptureError("raw byte count does not match manifest")
        if source.raw_sha256 != manifest.raw_sha256:
            raise PrivateRawCaptureError("raw digest does not match manifest")
        if sha256(raw_response_bytes).hexdigest() != source.raw_sha256:
            raise PrivateRawCaptureError("raw bytes do not match expected digest")
        locator_path = Path(source.locator)
        if locator_path.is_absolute() or ".." in locator_path.parts:
            raise PrivateRawCaptureError("private capture locator is unsafe")
        expected_file = self._root / locator_path
        if expected_file.name != "quote-response.json":
            raise PrivateRawCaptureError("private capture file name is unsafe")
        capture_dir = expected_file.parent
        self._ensure_private_parent(capture_dir.parent)
        if capture_dir.exists() or capture_dir.is_symlink():
            raise PrivateRawCaptureError("private capture identity already exists")

        temp_dir = capture_dir.parent / f".{capture_dir.name}.pending-{uuid4().hex}"
        try:
            temp_dir.mkdir(mode=0o700)
            self._write_private_file(temp_dir / "quote-response.json", raw_response_bytes)
            manifest_bytes = json.dumps(
                _manifest_json(manifest), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            self._write_private_file(temp_dir / "capture-manifest.json", manifest_bytes)
            os.rename(temp_dir, capture_dir)
        except OSError as exc:
            self._discard_pending(temp_dir)
            raise PrivateRawCaptureError("private raw capture commit failed") from exc

    def _require_root(self) -> None:
        if not self._root.is_absolute() or self._root.is_symlink() or not self._root.is_dir():
            raise PrivateRawCaptureError("private capture root must be an absolute directory")
        if stat.S_IMODE(self._root.stat().st_mode) != 0o700:
            raise PrivateRawCaptureError("private capture root must have mode 0700")

    def _ensure_private_parent(self, target: Path) -> None:
        relative = target.relative_to(self._root)
        current = self._root
        for component in relative.parts:
            current = current / component
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise PrivateRawCaptureError("private capture path is unsafe")
                if stat.S_IMODE(current.stat().st_mode) != 0o700:
                    raise PrivateRawCaptureError("private capture directory must have mode 0700")
            else:
                current.mkdir(mode=0o700)

    @staticmethod
    def _write_private_file(path: Path, body: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            written = 0
            while written < len(body):
                count = os.write(descriptor, body[written:])
                if count <= 0:
                    raise OSError("private capture write was incomplete")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _discard_pending(path: Path) -> None:
        if not path.exists() or path.is_symlink():
            return
        for filename in ("quote-response.json", "capture-manifest.json"):
            candidate = path / filename
            if candidate.exists() and candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
        try:
            path.rmdir()
        except OSError:
            pass


def _manifest_json(manifest: PrivateRawCaptureManifest) -> Mapping[str, object]:
    payload = asdict(manifest)
    payload["asof"] = manifest.asof.isoformat()
    for field in ("started_at", "received_at", "completed_at"):
        value = payload[field]
        assert isinstance(value, datetime)
        payload[field] = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return payload
