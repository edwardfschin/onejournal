"""Passkey-gated, credential-free intake of an exact manual capture package.

The default remains staging only. A separately enabled Mac Journal target can
save validated activity atomically; position packages still use staging only.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping
from threading import Lock
import duckdb

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
from onejournal.local_web import private_directory, private_file
from onejournal.provider_connectors.external_acquisition import (
    convert_external_schwab_lifecycle,
    convert_external_schwab_positions,
)
from onejournal.provider_connectors.usage_policy import ProviderUsagePolicy
from onejournal.refresh_capture_authorization import (
    ManualRefreshAuthorizationError,
    load_private_capture_authorization,
    verify_authorized_capture,
)


PREFIX = "/api/v1/local-owner/manual-capture"
CONTRACT = "onejournal.manual-capture-upload.v1"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_ACKNOWLEDGEMENT_BYTES = 256 * 1024
MAX_ACCOUNT_BINDING_BYTES = 256 * 1024


class ManualCaptureIntake:
    def __init__(self, *, authorization_path: Path, acknowledgement_path: Path,
                 account_binding_path: Path,
                 usage_policy: ProviderUsagePolicy, staging_root: Path,
                 project_root: Path):
        self.authorization_path = authorization_path
        self.acknowledgement_path = acknowledgement_path
        self.account_binding_path = account_binding_path
        self.usage_policy = usage_policy
        self.staging_root = private_directory(staging_root, "manual capture staging root")
        self.project_root = project_root
        if self.staging_root.is_relative_to(project_root.resolve()):
            raise ValueError("Manual capture staging must be outside the project checkout.")

    def stage(self, files: Mapping[str, bytes], *, journal_db: Path | None = None) -> dict[str, object]:
        authorization = load_private_capture_authorization(
            self.authorization_path, project_root=self.project_root
        )
        acknowledgement = private_file(
            self.acknowledgement_path, "capture acknowledgement", private_parent=True
        )
        with acknowledgement.open("rb") as stream:
            acknowledgement_bytes = stream.read(MAX_ACKNOWLEDGEMENT_BYTES + 1)
        if not 0 < len(acknowledgement_bytes) <= MAX_ACKNOWLEDGEMENT_BYTES:
            raise ValueError("Capture acknowledgement is missing or oversized.")
        acquisition = verify_authorized_capture(
            files,
            authorization=authorization,
            acknowledgement_bytes=acknowledgement_bytes,
            usage_policy=self.usage_policy,
            evaluated_at_utc=datetime.now(UTC),
        )
        account_binding_file = private_file(
            self.account_binding_path, "capture account binding", private_parent=True
        )
        with account_binding_file.open("rb") as stream:
            binding_bytes = stream.read(MAX_ACCOUNT_BINDING_BYTES + 1)
        if not 0 < len(binding_bytes) <= MAX_ACCOUNT_BINDING_BYTES:
            raise ValueError("Capture account binding is missing or oversized.")
        binding = load_schwab_position_private_binding_bytes(binding_bytes)
        if acquisition.manifest.connection_uid != binding.connection_uid:
            raise ValueError("Capture connection differs from the private account binding.")
        if authorization.capture_scope == "current_positions":
            converted = convert_external_schwab_positions(
                acquisition,
                provider_account_hash=binding.provider_account_hash,
                provider_account_number=binding.provider_account_number,
                source_account_id=binding.source_account_id,
                mappings=binding.mappings,
            )
            if not converted.snapshot.account_complete:
                raise ValueError("A complete current-position snapshot is required.")
        else:
            converted = convert_external_schwab_lifecycle(
                acquisition,
                provider_account_hash=binding.provider_account_hash,
                provider_account_number=binding.provider_account_number,
                source_account_id=binding.source_account_id,
            )
        root = private_directory(self.staging_root, "manual capture staging root")
        destination = root / acquisition.manifest_sha256
        if destination.exists() or destination.is_symlink():
            if not _exact_staged_files(destination, files):
                raise ValueError("Staged capture differs from the verified package.")
            replayed = True
        else:
            pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
            try:
                for name, body in files.items():
                    fd = os.open(pending / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as output:
                        output.write(body)
                        output.flush()
                        os.fsync(output.fileno())
                os.rename(pending, destination)
            finally:
                if pending.exists():
                    shutil.rmtree(pending)
            replayed = False
        receipt = {
            "contract_version": CONTRACT,
            "state": "verified_and_staged",
            "scope": authorization.capture_scope,
            "manifest_sha256": acquisition.manifest_sha256,
            "replayed": replayed,
            "journal_written": False,
            "financial_publication_authorized": False,
        }
        if journal_db is not None and authorization.capture_scope == 'activity':
            from onejournal.brokers.schwab.account_binding import (
                SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA, SchwabAccountPrivateBinding,
            )
            from onejournal.journal.activity_refresh_repository import append_activity_journal
            from onejournal.refresh_activity import confirmed_import, activity_plan
            account = SchwabAccountPrivateBinding(SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
                binding.connection_uid, binding.source_account_id,
                binding.provider_account_hash, binding.provider_account_number)
            baseline = confirmed_import(journal_db, account)
            with duckdb.connect(str(journal_db), read_only=True) as con:
                replay = con.execute('''SELECT artifact_json FROM incremental_activity_imports
                    WHERE source_broker='schwab' AND source_account_id=? AND acquisition_run_uid=?''',
                    [account.source_account_id, authorization.acquisition_run_uid]).fetchone()
            if replay:
                saved = json.loads(replay[0])
                if saved['manifest_sha256'] != authorization.manifest_sha256:
                    raise ValueError('Retained upload differs from this package.')
                plan = saved['plan']
                overlap = plan['overlap_days']
            else:
                overlap = (baseline.cutoff.date() - converted.window_start_date).days + 1
                if not 1 <= overlap <= 29:
                    raise ValueError('Upload does not overlap the last confirmed Journal import.')
                plan = activity_plan(baseline, account, asof=converted.window_end_date, overlap_days=overlap)
            result = append_activity_journal(db=journal_db, binding=account,
                asof=converted.window_end_date, overlap_days=overlap,
                expected_plan_sha256=plan['plan_sha256'], acquisition_root=destination,
                acknowledgement=self.acknowledgement_path, usage_policy=self.usage_policy,
                expected_run_uid=authorization.acquisition_run_uid,
                expected_approval_id=authorization.acquisition_approval_id,
                expected_owner_uid=authorization.owner_uid,
                expected_owner_epoch_uid=authorization.owner_epoch_uid, evaluated_at=datetime.now(UTC))
            receipt.update(state='journal_saved', replayed=result['replayed'],
                journal_written=True, new_records=result['new_records'],
                trade_count=result['trade_count'], execution_count=result['execution_count'])
        return receipt


def _exact_staged_files(directory: Path, files: Mapping[str, bytes]) -> bool:
    try:
        private_directory(directory, "staged capture")
        if {p.name for p in directory.iterdir()} != set(files):
            return False
        for name, body in files.items():
            path = private_file(directory / name, "staged capture file", private_parent=True)
            if path.read_bytes() != body:
                return False
    except (OSError, ValueError):
        return False
    return True


def _decode_upload(body: bytes) -> dict[str, bytes]:
    try:
        document = json.loads(body)
        if not isinstance(document, dict) or set(document) != {"files"}:
            raise ValueError
        items = document["files"]
        if not isinstance(items, list) or len(items) not in (2, 3):
            raise ValueError
        decoded: dict[str, bytes] = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"name", "content_base64"}:
                raise ValueError
            name, encoded = item["name"], item["content_base64"]
            if (not isinstance(name, str) or Path(name).name != name
                    or name in decoded or not isinstance(encoded, str)):
                raise ValueError
            decoded[name] = base64.b64decode(encoded, validate=True)
        return decoded
    except (UnicodeError, ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("Selected capture files are invalid.") from exc


def register_manual_capture_routes(app, intake: ManualCaptureIntake | None = None,
                                   *, journal_db=None, db_lock=None) -> None:
    lock = db_lock if db_lock is not None else Lock()
    @app.get(PREFIX)
    def status(request: Request):
        return {"contract_version": CONTRACT,
                "enabled": intake is not None and getattr(request.app.state, "passkey_access", None) is not None}

    @app.post(PREFIX, status_code=202)
    async def upload(request: Request):
        if getattr(request.app.state, "passkey_access", None) is None:
            raise HTTPException(403, "Protected owner access is required.")
        if intake is None:
            raise HTTPException(503, "Manual capture upload is not configured.")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "JSON is required.")
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Selected capture package is too large.")
        try:
            files = _decode_upload(body)
            def save():
                with lock:
                    return intake.stage(files, journal_db=journal_db)
            return await run_in_threadpool(save)
        except (OSError, ValueError, duckdb.Error, ManualRefreshAuthorizationError):
            raise HTTPException(422, "Capture was not verified or staged. Saved results are unchanged.") from None
