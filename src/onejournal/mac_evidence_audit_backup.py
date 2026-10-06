"""Encrypted Mac recovery for accepted Phase 1 source evidence and security audit.

This image complements, but never replaces, the existing journal and access
images. In particular it must not copy the passkey security database itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import tempfile

import duckdb

from onejournal.local_web import load_config, private_file
from onejournal.mac_access_backup import disk_image, password_bytes, private_output, validate_destination
from onejournal.mac_journal_backup import copy_private, file_hash
from onejournal.passkey_access import CONTRACT as ACCESS_CONTRACT


VERSION = "onejournal.mac-evidence-audit-backup.v1"
FAMILY_TABLES = (
    "phase1_schwab_evidence_import_families",
    "phase1_schwab_evidence_v2_import_families",
)
AUDIT_ACTIONS = frozenset({"offline_provision", "offline_recovery", "request", "register_options", "register", "login", "logout"})
AUDIT_OUTCOMES = frozenset({"accepted", "denied"})
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
README = """OneJournal Mac source-evidence and security-audit recovery

This encrypted image contains only the original JSON files whose SHA-256
fingerprints are recorded in the journal's persisted Phase 1 Schwab v1/v2
evidence families, and the value-free security event history at capture time.
It does not contain a journal, access setup, passkeys, security database,
enrollment grant, broker credential or live session. Keep the separate journal
and access images and their passwords. This is Mac-only, point-in-time recovery.

For actual loss, unlock privately and restore into a NEW owner-only directory,
never over live files. Verify every file against the manifest and the separately
restored journal's source fingerprints before re-import or use. The audit JSON
is historical evidence, not a security database to activate. Do not restore old
passkeys, counters, sessions or grants. Restore access with the approved offline
fresh-enrollment procedure. This image does not authorize hosted deployment,
broker access, trading, or a production disaster-recovery claim.

Keep the password separate from the USB. Future imports or audit events require
a fresh image; this point-in-time image does not cover them automatically.
"""


def _private_directory(path: Path, label: str) -> Path:
    if (not path.is_absolute() or path.is_symlink() or not path.is_dir() or
            path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o700):
        raise ValueError(f"{label} must be an owner-only, non-symlink directory (0700).")
    return path.resolve()


def _relative_name(name: str) -> PurePosixPath:
    if not isinstance(name, str):
        raise ValueError("The recovery manifest has an unsafe evidence path.")
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or
            any(part in {"", ".", ".."} for part in path.parts) or path.suffix != ".json" or
            str(path) != name):
        raise ValueError("The recovery manifest has an unsafe evidence path.")
    return path


def source_digests(journal: Path) -> set[str]:
    private_file(journal, "journal")
    values: set[str] = set()
    with duckdb.connect(str(journal), read_only=True) as con:
        family_count = 0
        for table in FAMILY_TABLES:
            rows = con.execute(
                f"SELECT source_manifest_sha256s_json, source_raw_sha256s_json FROM {table}"
            ).fetchall()
            family_count += len(rows)
            for row in rows:
                for encoded in row:
                    items = json.loads(encoded)
                    if not isinstance(items, list) or not items:
                        raise ValueError("Persisted source lineage is incomplete.")
                    for value in items:
                        if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
                            raise ValueError("Persisted source lineage contains an invalid fingerprint.")
                        values.add(value)
    if family_count == 0 or not values:
        raise ValueError("No persisted Phase 1 source lineage is available.")
    return values


def exact_evidence(raw_root: Path, required: set[str]) -> dict[str, tuple[Path, str]]:
    root = _private_directory(raw_root, "Private evidence root")
    found: dict[str, tuple[Path, str]] = {}
    for path in root.rglob("*.json"):
        if not path.is_file() or path.is_symlink():
            continue
        observed = file_hash(path)
        if observed not in required:
            continue
        relative = path.relative_to(root)
        if any(parent.is_symlink() or parent.stat().st_uid != os.getuid() or
               parent.stat().st_mode & 0o777 != 0o700 for parent in (path.parent, *path.parents[:len(relative.parts)-1])):
            raise ValueError("Matched evidence has an unsafe parent directory.")
        private_file(path, "matched source evidence")
        name = relative.as_posix()
        _relative_name(name)
        if name in found:
            raise ValueError("Matched evidence path is duplicated.")
        found[name] = (path, observed)
    if {digest for _, digest in found.values()} != required:
        raise ValueError("An accepted source fingerprint is missing from private evidence.")
    folded = [name.casefold() for name in found]
    if len(folded) != len(set(folded)):
        raise ValueError("Evidence paths collide on the Mac recovery filesystem.")
    return found


def audit_history(security_db: Path, journal: Path, origin: str) -> list[list[object]]:
    private_file(security_db, "security store", private_parent=True)
    if Path(str(security_db) + ".wal").exists():
        raise ValueError("The security store has a pending log; stop the protected site cleanly.")
    try:
        with duckdb.connect(str(security_db), read_only=True) as con:
            columns = [(row[1], row[2]) for row in con.execute("PRAGMA table_info('access_audit')").fetchall()]
            if columns != [("occurred_at", "DOUBLE"), ("action", "VARCHAR"), ("outcome", "VARCHAR")]:
                raise ValueError("Security audit schema is not the approved value-free contract.")
            binding = con.execute("SELECT version, origin, journal_digest FROM access_meta").fetchall()
            expected = (ACCESS_CONTRACT, origin, hashlib.sha256(str(journal.resolve()).encode()).hexdigest())
            if binding != [expected]:
                raise ValueError("Security audit does not match this owner, journal and local origin.")
            rows = con.execute("SELECT occurred_at, action, outcome FROM access_audit ORDER BY occurred_at, action, outcome").fetchall()
    except duckdb.Error:
        raise ValueError("Security audit is unavailable while the protected site holds its store; stop it cleanly first.") from None
    result: list[list[object]] = []
    for stamp, action, outcome in rows:
        if (type(stamp) is not float or not math.isfinite(stamp) or
                action not in AUDIT_ACTIONS or outcome not in AUDIT_OUTCOMES):
            raise ValueError("Security audit contains an unexpected value; nothing was backed up.")
        result.append([stamp, action, outcome])
    return result


def _copy_tree(source: Path, target: Path, names: list[str]) -> None:
    for name in names:
        original = source / name
        if original.is_symlink() or not original.is_file() or any(parent.is_symlink() for parent in original.parents if parent == source or source in parent.parents):
            raise ValueError("The recovery image has an unsafe evidence file.")
        destination = target / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.parent.stat().st_mode & 0o777 != 0o700:
            raise ValueError("Recovery staging directory is not owner-only.")
        copy_private(original, destination)


def snapshot(config_path: Path, security_db: Path, raw_root: Path, stage: Path, project_root: Path) -> dict:
    config = load_config(config_path, project_root)
    _private_directory(stage, "Temporary recovery snapshot")
    if any(stage.iterdir()):
        raise ValueError("Use an empty temporary recovery snapshot.")
    audit = audit_history(security_db, config.journal_db, f"https://localhost:{config.web_port}")
    required = source_digests(config.journal_db)
    matched = exact_evidence(raw_root, required)
    raw_stage = stage / "evidence"
    raw_stage.mkdir(mode=0o700)
    hashes: dict[str, str] = {}
    for name, (source, digest) in sorted(matched.items()):
        target = raw_stage / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        copy_private(source, target)
        if file_hash(source) != digest or file_hash(target) != digest:
            raise ValueError("Private source evidence changed during capture.")
        hashes[name] = digest
    audit_document = {"contract_version": VERSION, "events": audit}
    private_output(stage / "audit.json", json.dumps(audit_document, sort_keys=True, separators=(",", ":")).encode())
    private_output(stage / "RECOVERY.txt", README.encode())
    manifest = {
        "contract_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprints": sorted(required),
        "evidence_sha256": hashes,
        "audit_events": len(audit),
        "audit_sha256": file_hash(stage / "audit.json"),
        "instructions_sha256": file_hash(stage / "RECOVERY.txt"),
    }
    private_output(stage / "manifest.json", json.dumps(manifest, sort_keys=True).encode())
    verify_restored(stage, manifest)
    return manifest


def verify_restored(root: Path, manifest: dict) -> tuple[int, int]:
    if not isinstance(manifest, dict) or manifest.get("contract_version") != VERSION:
        raise ValueError("The evidence recovery manifest has an unsupported version.")
    if set(manifest) != {"contract_version", "created_at", "source_fingerprints", "evidence_sha256", "audit_events", "audit_sha256", "instructions_sha256"}:
        raise ValueError("The evidence recovery manifest has unsupported fields.")
    hashes = manifest["evidence_sha256"]
    fingerprints = manifest["source_fingerprints"]
    if (not isinstance(hashes, dict) or not hashes or not isinstance(fingerprints, list) or not fingerprints or
            any(not isinstance(value, str) or DIGEST.fullmatch(value) is None for value in fingerprints) or
            fingerprints != sorted(set(fingerprints)) or
            set(hashes.values()) != set(fingerprints) or
            any(not isinstance(name, str) or not isinstance(value, str) or DIGEST.fullmatch(value) is None for name, value in hashes.items()) or
            any(not isinstance(manifest[key], str) or DIGEST.fullmatch(manifest[key]) is None for key in ("audit_sha256", "instructions_sha256")) or
            type(manifest["audit_events"]) is not int or manifest["audit_events"] < 0):
        raise ValueError("The evidence recovery manifest is incomplete or invalid.")
    for name, expected in hashes.items():
        _relative_name(name)
        if file_hash(private_file(root / "evidence" / name, "restored evidence")) != expected:
            raise ValueError("Restored evidence does not match accepted source lineage.")
    if file_hash(private_file(root / "audit.json", "restored audit")) != manifest["audit_sha256"]:
        raise ValueError("Restored audit does not match its recovery manifest.")
    if file_hash(private_file(root / "RECOVERY.txt", "recovery instructions")) != manifest["instructions_sha256"]:
        raise ValueError("Restored recovery instructions do not match.")
    document = json.loads((root / "audit.json").read_bytes())
    rows = document.get("events") if isinstance(document, dict) and document.get("contract_version") == VERSION and set(document) == {"contract_version", "events"} else None
    if not isinstance(rows, list) or len(rows) != manifest["audit_events"]:
        raise ValueError("Restored security audit is incomplete.")
    for row in rows:
        if (not isinstance(row, list) or len(row) != 3 or type(row[0]) not in {float, int} or
                not math.isfinite(row[0]) or row[1] not in AUDIT_ACTIONS or row[2] not in AUDIT_OUTCOMES):
            raise ValueError("Restored security audit has an unexpected event.")
    return len(hashes), len(rows)


def verify_backup(image: Path, password: str, expected: dict | None = None) -> tuple[int, int]:
    password_bytes(password)
    if not image.is_absolute() or image.is_symlink() or not image.is_file():
        raise ValueError("Choose an existing non-symlink encrypted evidence image.")
    if plistlib.loads(disk_image(["isencrypted", str(image), "-plist"])).get("encrypted") is not True:
        raise ValueError("The evidence recovery image is not encrypted.")
    disk_image(["verify", str(image), "-stdinpass", "-quiet"], password)
    with tempfile.TemporaryDirectory(prefix="onejournal-evidence-restore-") as folder:
        root = Path(folder).resolve()
        mount, restored = root / "mounted", root / "restored"
        mount.mkdir(mode=0o700)
        restored.mkdir(mode=0o700)
        attached = False
        try:
            disk_image(["attach", str(image), "-readonly", "-noautoopen", "-nobrowse", "-mountpoint", str(mount), "-stdinpass", "-quiet"], password)
            attached = True
            manifest_file = mount / "manifest.json"
            if manifest_file.is_symlink() or not manifest_file.is_file() or manifest_file.stat().st_size > 1024 * 1024:
                raise ValueError("The evidence recovery manifest is invalid.")
            manifest = json.loads(manifest_file.read_bytes())
            if expected is not None and manifest != expected:
                raise ValueError("Published image differs from the captured evidence and audit.")
            names = manifest.get("evidence_sha256") if isinstance(manifest, dict) else None
            if not isinstance(names, dict):
                raise ValueError("The evidence recovery manifest is invalid.")
            for name in names:
                _relative_name(name)
            for name in ("audit.json", "RECOVERY.txt"):
                if (mount / name).is_symlink() or not (mount / name).is_file():
                    raise ValueError("The recovery image has an unsafe file.")
                copy_private(mount / name, restored / name)
            (restored / "evidence").mkdir(mode=0o700)
            _copy_tree(mount / "evidence", restored / "evidence", sorted(names))
            return verify_restored(restored, manifest)
        finally:
            if attached:
                disk_image(["detach", str(mount), "-quiet"])


def create_backup(config_path: Path, security_db: Path, raw_root: Path, destination: Path,
                  password: str, project_root: Path, *, require_usb: bool = True) -> tuple[int, int]:
    password_bytes(password)
    validate_destination(destination, require_usb=require_usb)
    with tempfile.TemporaryDirectory(prefix="onejournal-evidence-backup-") as folder:
        root = Path(folder).resolve()
        stage, mount = root / "snapshot", root / "mounted"
        stage.mkdir(mode=0o700)
        mount.mkdir(mode=0o700)
        manifest = snapshot(config_path, security_db, raw_root, stage, project_root)
        working, image = root / "working.dmg", root / "encrypted.dmg"
        total = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
        disk_image(["create", str(working), "-size", f"{math.ceil(total / 1048576) + 32}m", "-fs", "HFS+", "-volname", "OneJournal evidence recovery", "-quiet"])
        attached = False
        try:
            disk_image(["attach", str(working), "-noautoopen", "-nobrowse", "-mountpoint", str(mount), "-quiet"])
            attached = True
            mount.chmod(0o700)
            for name in ("manifest.json", "audit.json", "RECOVERY.txt"):
                copy_private(stage / name, mount / name)
            (mount / "evidence").mkdir(mode=0o700)
            _copy_tree(stage / "evidence", mount / "evidence", sorted(manifest["evidence_sha256"]))
        finally:
            if attached:
                disk_image(["detach", str(mount), "-quiet"])
        disk_image(["convert", str(working), "-o", str(image), "-format", "UDZO", "-encryption", "AES-256", "-stdinpass", "-quiet"], password)
        verify_backup(image, password, manifest)
        validate_destination(destination, require_usb=require_usb)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output, image.open("rb") as original:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            return verify_backup(destination, password, manifest)
        except BaseException:
            destination.unlink(missing_ok=True)  # Only our newly reserved incomplete image.
            raise
