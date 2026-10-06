"""Bounded Mac journal recovery; no live writes, service or credential changes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import tempfile

import duckdb

from onejournal.local_web import configured_app, load_config, parse_config, private_file
from onejournal.mac_access_backup import disk_image, password_bytes, private_output, validate_destination

VERSION = "onejournal.mac-journal-backup.v1"
REQUIRED = {"journal.duckdb", "local-web.json", "RECOVERY.txt"}
AUTH_FILES = {"broker_current_authorization": "broker-current-authorization.json",
              "reporting_authorization": "reporting-authorization.json"}
README = """OneJournal Mac journal recovery

This image contains the complete operational journal, original local website
configuration and only its referenced exact portfolio/report release files.
It is separate from the existing encrypted access-setup image. It contains no
broker credentials, TLS private key, passkey store, session or enrollment grant.
Raw source evidence outside the journal and security audit are not backed up by
this image. Those remain separate recovery needs; this is not full disaster recovery.

Recovery rehearsal uses only temporary owner-private files. It checks exact
file hashes, all journal table/view counts and column definitions, and existing
read-only API startup/release validation. It never starts an unauthenticated API,
recalculates financial results, migrates data or restores over live files.

For actual loss: unlock privately and restore into a NEW owner-private directory
(0700; files 0600), not an existing journal or source checkout. Deliberately update
the restored configuration's journal/release paths to those restored files.
Check it against compatible OneJournal code and the same exact accepted releases.
Do not start the legacy unauthenticated launcher. Restore access setup separately,
review localhost certificate expiry/trust, and use the protected passkey launcher.
Never restore old security keys/counters or assume localhost passkeys work at a
new production domain. Lost access needs the existing owner-authorized offline
procedure with stopped services and fresh enrollment. This image grants no reset,
activation, live overwrite, hosted/VPS, provider or trading authority.

Keep the image password independently of the USB. Losing it makes the backup
unusable. This is a dated point-in-time backup, not a recurring backup policy.
"""


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def copy_private(source: Path, target: Path) -> None:
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output, source.open("rb") as original:
        shutil.copyfileobj(original, output)
        output.flush()
        os.fsync(output.fileno())


def inventory(con) -> dict:
    relations = con.execute("SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()
    counts = {}
    for schema, name, _kind in relations:
        quoted = '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"'
        counts[name] = con.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
    columns = con.execute("SELECT table_schema, table_name, column_name, ordinal_position, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='main' ORDER BY table_name, ordinal_position").fetchall()
    return {"relations": [list(row) for row in relations], "columns": [list(row) for row in columns], "counts": counts}


def snapshot(config_path: Path, stage: Path, project_root: Path) -> dict:
    """Hold a read-only DB lock only for snapshot capture, never for encryption."""
    config = load_config(config_path, project_root)
    if stage.is_symlink() or stage.resolve() != stage or stage.stat().st_mode & 0o777 != 0o700 or stage.stat().st_uid != os.getuid() or any(stage.iterdir()):
        raise ValueError("Use an empty owner-private temporary snapshot directory.")
    wal = Path(str(config.journal_db) + ".wal")
    if wal.exists():
        raise ValueError("The journal has a pending write-ahead log. No checkpoint or restart was attempted.")
    sources = {"journal.duckdb": config.journal_db, "local-web.json": private_file(config_path, "backup configuration", private_parent=True)}
    for field, path in (("broker_current_authorization", config.broker_authorization), ("reporting_authorization", config.reporting_authorization)):
        if path is not None:
            sources[AUTH_FILES[field]] = path
    try:
        with duckdb.connect(str(config.journal_db), read_only=True) as con:
            if wal.exists():
                raise ValueError("A pending journal log appeared; no snapshot was taken.")
            configured_app(config)  # Existing read-only schema and exact-release authority.
            expected = {name: file_hash(path) for name, path in sources.items()}
            state = inventory(con)
            for name, path in sources.items():
                copy_private(path, stage / name)
            if (wal.exists() or expected != {name: file_hash(path) for name, path in sources.items()} or
                    expected != {name: file_hash(stage / name) for name in sources}):
                raise ValueError("Snapshot inputs changed; the backup was not published.")
    except duckdb.Error:
        raise ValueError("A consistent read-only journal snapshot is unavailable. No writer, checkpoint or service was changed.") from None
    private_output(stage / "RECOVERY.txt", README.encode())
    expected["RECOVERY.txt"] = file_hash(stage / "RECOVERY.txt")
    manifest = {"contract_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "sha256": expected, "inventory": state}
    private_output(stage / "manifest.json", json.dumps(manifest, sort_keys=True).encode())
    return manifest


def verify_restored(root: Path, manifest: dict, project_root: Path) -> int:
    hashes = manifest.get("sha256")
    if (manifest.get("contract_version") != VERSION or not isinstance(hashes, dict) or
            not REQUIRED.issubset(hashes) or set(hashes) - REQUIRED - set(AUTH_FILES.values()) or
            any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes.values())):
        raise ValueError("The journal recovery manifest has unsupported contents.")
    for name, expected in hashes.items():
        if file_hash(private_file(root / name, "restored file", private_parent=True)) != expected:
            raise ValueError("Restored files do not match the backup.")
    document = json.loads((root / "local-web.json").read_bytes())
    document["journal_db_path"] = str(root / "journal.duckdb")
    for field, name in AUTH_FILES.items():
        if bool(document.get(field)) != (name in hashes):
            raise ValueError("The backup is missing or has unexpected release authority.")
        if name in hashes:
            document[field] = str(root / name)
    config = parse_config(document)
    with duckdb.connect(str(config.journal_db), read_only=True) as con:
        if inventory(con) != manifest.get("inventory"):
            raise ValueError("Restored journal schema or record counts do not match.")
        configured_app(config)  # No requests, readers' audits, server or migration.
    if file_hash(config.journal_db) != hashes["journal.duckdb"]:
        raise ValueError("Restoration validation changed the disposable journal.")
    return len(manifest["inventory"]["relations"])


def verify_backup(image: Path, password: str, project_root: Path, expected: dict | None = None) -> int:
    password_bytes(password)
    if not image.is_absolute() or image.is_symlink() or not image.is_file():
        raise ValueError("Choose an existing non-symlink encrypted journal image.")
    if plistlib.loads(disk_image(["isencrypted", str(image), "-plist"])).get("encrypted") is not True:
        raise ValueError("The journal recovery image is not encrypted.")
    disk_image(["verify", str(image), "-stdinpass", "-quiet"], password)
    with tempfile.TemporaryDirectory(prefix="onejournal-journal-restore-") as folder:
        root = Path(folder).resolve()
        mount, restored = root / "mounted", root / "restored"
        mount.mkdir(mode=0o700)
        restored.mkdir(mode=0o700)
        attached = False
        try:
            disk_image(["attach", str(image), "-readonly", "-noautoopen", "-nobrowse", "-mountpoint", str(mount), "-stdinpass", "-quiet"], password)
            attached = True
            manifest_path = mount / "manifest.json"
            if manifest_path.is_symlink() or manifest_path.stat().st_size > 1024 * 1024:
                raise ValueError("The journal recovery manifest is invalid.")
            manifest = json.loads(manifest_path.read_bytes())
            if expected is not None and manifest != expected:
                raise ValueError("Published recovery image does not match the captured snapshot.")
            # Check the fixed allowlist before constructing any destination path.
            names = manifest.get("sha256") if isinstance(manifest, dict) else None
            if not isinstance(names, dict) or not REQUIRED.issubset(names) or set(names) - REQUIRED - set(AUTH_FILES.values()):
                raise ValueError("The recovery image has unsupported files.")
            for name in names:
                source = mount / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError("The recovery image has invalid files.")
                copy_private(source, restored / name)
            return verify_restored(restored, manifest, project_root)
        finally:
            if attached:
                disk_image(["detach", str(mount), "-quiet"])


def create_backup(config_path: Path, destination: Path, password: str, project_root: Path, *, require_usb: bool = True) -> int:
    password_bytes(password)
    validate_destination(destination, require_usb=require_usb)
    with tempfile.TemporaryDirectory(prefix="onejournal-journal-backup-") as folder:
        root = Path(folder).resolve()
        stage, mount = root / "snapshot", root / "mounted"
        stage.mkdir(mode=0o700)
        mount.mkdir(mode=0o700)
        manifest = snapshot(config_path, stage, project_root)
        verify_restored(stage, manifest, project_root)
        working, image = root / "working.dmg", root / "encrypted.dmg"
        size_mb = math.ceil(sum(path.stat().st_size for path in stage.iterdir()) / 1048576) + 32
        disk_image(["create", str(working), "-size", f"{size_mb}m", "-fs", "HFS+", "-volname", "OneJournal journal recovery", "-quiet"])
        attached = False
        try:
            disk_image(["attach", str(working), "-noautoopen", "-nobrowse", "-mountpoint", str(mount), "-quiet"])
            attached = True
            mount.chmod(0o700)
            for path in stage.iterdir():
                copy_private(path, mount / path.name)
        finally:
            if attached:
                disk_image(["detach", str(mount), "-quiet"])
        disk_image(["convert", str(working), "-o", str(image), "-format", "UDZO", "-encryption", "AES-256", "-stdinpass", "-quiet"], password)
        verify_backup(image, password, project_root, manifest)
        validate_destination(destination, require_usb=require_usb)
        # Reserve O_EXCL before the cleanup block so an existing file is preserved.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output, image.open("rb") as original:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            return verify_backup(destination, password, project_root, manifest)
        except BaseException:
            destination.unlink(missing_ok=True)  # Only our newly reserved incomplete image.
            raise
