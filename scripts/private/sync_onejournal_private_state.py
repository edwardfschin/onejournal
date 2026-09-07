#!/usr/bin/env python3
"""Plan or apply a fail-closed OneJournal private-workstation handoff.

Immutable vault files are merged without overwrite or deletion.  The operational
DuckDB is transferred separately through a checksum-verified staging file and
an atomic destination replacement.  The command never contacts a broker and
never discovers a database outside the two explicitly supplied vault roots.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


CONTRACT_VERSION = "onejournal.private-workstation-handoff.v1"
DEFAULT_VAULT_ROOT = Path("/Users/edward/Projects/Private/OneJournal")
DATABASE_RELATIVE_PATH = "journal/onejournal-local-owner-v1.duckdb"
LOCK_DIRECTORY_NAME = ".onejournal-private-sync.lock"
IGNORED_DIRECTORY_NAMES = {"__pycache__"}
IGNORED_EMPTY_RELATIVE_DIRECTORIES = {DATABASE_RELATIVE_PATH + ".tmp"}
REMOTE_NAME_RE = re.compile(r"[A-Za-z0-9_.@-]+")
REMOTE_PATH_RE = re.compile(r"/[A-Za-z0-9_./-]+")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SSH_OPTIONS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)


class PrivateStateSyncError(RuntimeError):
    """Raised when a private handoff safety invariant is not satisfied."""


@dataclass(frozen=True)
class FileRecord:
    sha256: str
    size: int


@dataclass(frozen=True)
class VaultInventory:
    files: Mapping[str, FileRecord]
    fingerprint: str

    @property
    def database(self) -> FileRecord | None:
        return self.files.get(DATABASE_RELATIVE_PATH)


@dataclass(frozen=True)
class SyncPlan:
    contract_version: str
    operator_sha256: str
    connection_sha256: str
    direction: str
    source_label: str
    target_label: str
    source_fingerprint: str
    target_fingerprint: str
    immutable_additions: tuple[str, ...]
    target_only_files: tuple[str, ...]
    conflicts: tuple[str, ...]
    source_database_sha256: str
    target_database_sha256: str | None
    plan_fingerprint: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _open_handle_count(path: Path) -> int:
    if not path.exists():
        return 0
    result = subprocess.run(
        ["lsof", "-t", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return 0
    if result.returncode != 0:
        raise PrivateStateSyncError("unable to verify local database handles")
    return len([line for line in result.stdout.splitlines() if line.strip()])


def inspect_local_vault(
    root: Path,
    *,
    allowed_lock_id: str | None = None,
    handle_counter: Callable[[Path], int] = _open_handle_count,
) -> VaultInventory:
    """Return a content inventory after enforcing private-vault invariants."""

    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise PrivateStateSyncError("vault root must be an absolute non-symlink directory")
    if _mode(root) != 0o700:
        raise PrivateStateSyncError("vault root must have mode 0700")

    lock_root = root / LOCK_DIRECTORY_NAME
    if lock_root.exists():
        if allowed_lock_id is None:
            raise PrivateStateSyncError("private transfer lock already exists")
        _validate_lock(lock_root, allowed_lock_id)

    files: dict[str, FileRecord] = {}
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path == lock_root:
            directory_names[:] = []
            continue
        for name in tuple(directory_names):
            path = current_path / name
            if path == lock_root:
                directory_names.remove(name)
                continue
            relative = path.relative_to(root).as_posix()
            if name in IGNORED_DIRECTORY_NAMES:
                directory_names.remove(name)
                continue
            if relative in IGNORED_EMPTY_RELATIVE_DIRECTORIES:
                if any(path.iterdir()):
                    raise PrivateStateSyncError(
                        "DuckDB temporary directory is not empty; close the writer"
                    )
                directory_names.remove(name)
                continue
            if path.is_symlink() or not path.is_dir() or _mode(path) != 0o700:
                raise PrivateStateSyncError("vault directories must be non-symlink mode 0700")
        for name in file_names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if "\n" in relative or "\r" in relative:
                raise PrivateStateSyncError("vault paths must not contain line breaks")
            if path.is_symlink() or not path.is_file() or _mode(path) != 0o600:
                raise PrivateStateSyncError("vault files must be regular non-symlink mode 0600")
            if relative.endswith(".duckdb.wal"):
                raise PrivateStateSyncError("DuckDB WAL exists; close the writer before handoff")
            files[relative] = FileRecord(
                sha256=_file_sha256(path),
                size=path.stat().st_size,
            )

    database_path = root / DATABASE_RELATIVE_PATH
    if handle_counter(database_path):
        raise PrivateStateSyncError("operational database has an open local handle")
    payload = {
        path: {"sha256": record.sha256, "size": record.size}
        for path, record in sorted(files.items())
    }
    return VaultInventory(files=files, fingerprint=_digest(payload))


REMOTE_HELPER = r'''
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

DB_REL = "journal/onejournal-local-owner-v1.duckdb"
LOCK_NAME = ".onejournal-private-sync.lock"
IGNORED_NAMES = {"__pycache__"}
IGNORED_EMPTY_DIRS = {DB_REL + ".tmp"}

def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            value.update(block)
    return value.hexdigest()

def mode(path):
    return stat.S_IMODE(path.lstat().st_mode)

def require_root(root):
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError("vault root must be an absolute non-symlink directory")
    if mode(root) != 0o700:
        raise RuntimeError("vault root must have mode 0700")

def open_handles(path):
    if not path.exists():
        return 0
    result = subprocess.run(["lsof", "-t", str(path)], capture_output=True, text=True)
    if result.returncode == 1:
        return 0
    if result.returncode != 0:
        raise RuntimeError("unable to verify remote database handles")
    return len([line for line in result.stdout.splitlines() if line.strip()])

def validate_lock(lock_root, transfer_id):
    owner = lock_root / "owner.json"
    if lock_root.is_symlink() or not lock_root.is_dir() or mode(lock_root) != 0o700:
        raise RuntimeError("remote transfer lock is invalid")
    if owner.is_symlink() or not owner.is_file() or mode(owner) != 0o600:
        raise RuntimeError("remote transfer lock owner is invalid")
    if json.loads(owner.read_text(encoding="utf-8")) != {"transfer_id": transfer_id}:
        raise RuntimeError("remote transfer lock belongs to another operation")

def inventory(root, allowed_lock_id=None):
    require_root(root)
    lock_root = root / LOCK_NAME
    if lock_root.exists():
        if allowed_lock_id is None:
            raise RuntimeError("private transfer lock already exists")
        validate_lock(lock_root, allowed_lock_id)
    files = {}
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path == lock_root:
            directories[:] = []
            continue
        for name in tuple(directories):
            path = current_path / name
            if path == lock_root:
                directories.remove(name)
                continue
            relative = path.relative_to(root).as_posix()
            if name in IGNORED_NAMES:
                directories.remove(name)
                continue
            if relative in IGNORED_EMPTY_DIRS:
                if any(path.iterdir()):
                    raise RuntimeError("DuckDB temporary directory is not empty; close the writer")
                directories.remove(name)
                continue
            if path.is_symlink() or not path.is_dir() or mode(path) != 0o700:
                raise RuntimeError("vault directories must be non-symlink mode 0700")
        for name in names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if "\n" in relative or "\r" in relative:
                raise RuntimeError("vault paths must not contain line breaks")
            if path.is_symlink() or not path.is_file() or mode(path) != 0o600:
                raise RuntimeError("vault files must be regular non-symlink mode 0600")
            if relative.endswith(".duckdb.wal"):
                raise RuntimeError("DuckDB WAL exists; close the writer before handoff")
            files[relative] = {"sha256": digest_file(path), "size": path.stat().st_size}
    database = root / DB_REL
    if open_handles(database):
        raise RuntimeError("operational database has an open remote handle")
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"files": files, "fingerprint": hashlib.sha256(canonical).hexdigest()}

def acquire(root, transfer_id):
    require_root(root)
    lock_root = root / LOCK_NAME
    lock_root.mkdir(mode=0o700)
    owner = lock_root / "owner.json"
    owner.write_text(json.dumps({"transfer_id": transfer_id}, sort_keys=True), encoding="utf-8")
    owner.chmod(0o600)
    return {"locked": True}

def release(root, transfer_id):
    lock_root = root / LOCK_NAME
    validate_lock(lock_root, transfer_id)
    (lock_root / "owner.json").unlink()
    lock_root.rmdir()
    return {"released": True}

def prepare_incoming(root, transfer_id, expected_target_sha):
    validate_lock(root / LOCK_NAME, transfer_id)
    journal = root / "journal"
    if journal.exists():
        if journal.is_symlink() or not journal.is_dir() or mode(journal) != 0o700:
            raise RuntimeError("journal directory must be non-symlink mode 0700")
    else:
        journal.mkdir(mode=0o700)
    current = root / DB_REL
    if open_handles(current):
        raise RuntimeError("destination database has an open handle")
    if Path(str(current) + ".wal").exists():
        raise RuntimeError("destination database WAL exists")
    actual = digest_file(current) if current.exists() else None
    if actual != expected_target_sha:
        raise RuntimeError("destination database changed after planning")
    incoming = journal / ("." + current.name + ".incoming-" + transfer_id)
    if incoming.exists() or incoming.is_symlink():
        raise RuntimeError("destination staging file already exists")
    return {"incoming": incoming.as_posix()}

def finalize(root, transfer_id, expected_source_sha, expected_target_sha, stamp):
    validate_lock(root / LOCK_NAME, transfer_id)
    current = root / DB_REL
    incoming = current.parent / ("." + current.name + ".incoming-" + transfer_id)
    if incoming.is_symlink() or not incoming.is_file() or mode(incoming) != 0o600:
        raise RuntimeError("destination staging file is not private and regular")
    if digest_file(incoming) != expected_source_sha:
        raise RuntimeError("destination staging checksum mismatch")
    if open_handles(current):
        raise RuntimeError("destination database acquired an open handle")
    actual = digest_file(current) if current.exists() else None
    if actual != expected_target_sha:
        raise RuntimeError("destination database changed before activation")
    backup = None
    if current.exists() and actual != expected_source_sha:
        backup_root = current.parent / "transfer-backups"
        if backup_root.exists():
            if backup_root.is_symlink() or not backup_root.is_dir() or mode(backup_root) != 0o700:
                raise RuntimeError("transfer backup directory is invalid")
        else:
            backup_root.mkdir(mode=0o700)
        backup = backup_root / ("onejournal-local-owner-v1.pre-transfer-" + stamp + "-" + actual[:12] + ".duckdb")
        if backup.exists():
            raise RuntimeError("transfer backup target already exists")
        shutil.copy2(current, backup)
        backup.chmod(0o600)
        if digest_file(backup) != actual:
            raise RuntimeError("destination backup checksum mismatch")
    os.replace(incoming, current)
    current.chmod(0o600)
    if digest_file(current) != expected_source_sha:
        raise RuntimeError("activated destination database checksum mismatch")
    return {"database_sha256": expected_source_sha, "backup_created": backup is not None}

def discard(root, transfer_id):
    validate_lock(root / LOCK_NAME, transfer_id)
    current = root / DB_REL
    incoming = current.parent / ("." + current.name + ".incoming-" + transfer_id)
    if incoming.exists() and not incoming.is_symlink() and incoming.is_file():
        incoming.unlink()
    return {"discarded": True}

def secure_additions(root, transfer_id, relative_paths):
    validate_lock(root / LOCK_NAME, transfer_id)
    secured_directories = set()
    for relative in relative_paths:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or not relative_path.parts:
            raise RuntimeError("immutable addition contains an unsafe path")
        path = root / relative_path
        if path.is_symlink():
            raise RuntimeError("immutable addition is not a regular file")
        if not path.exists():
            continue
        if not path.is_file():
            raise RuntimeError("immutable addition is not a regular file")
        path.chmod(0o600)
        parent = path.parent
        while parent != root:
            if parent.is_symlink() or not parent.is_dir():
                raise RuntimeError("immutable addition parent is not a regular directory")
            parent.chmod(0o700)
            secured_directories.add(parent.as_posix())
            parent = parent.parent
    return {"files_secured": len(relative_paths), "directories_secured": len(secured_directories)}

request = json.loads(sys.stdin.readline())
root = Path(request["root"])
action = request["action"]
if action == "inventory":
    result = inventory(root, request.get("allowed_lock_id"))
elif action == "acquire":
    result = acquire(root, request["transfer_id"])
elif action == "release":
    result = release(root, request["transfer_id"])
elif action == "prepare_incoming":
    result = prepare_incoming(root, request["transfer_id"], request.get("expected_target_sha"))
elif action == "finalize":
    result = finalize(root, request["transfer_id"], request["expected_source_sha"], request.get("expected_target_sha"), request["stamp"])
elif action == "discard":
    result = discard(root, request["transfer_id"])
elif action == "secure_additions":
    result = secure_additions(root, request["transfer_id"], request["relative_paths"])
else:
    raise RuntimeError("unsupported remote action")
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''


def _validate_remote(
    host: str,
    root: str,
    *,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> None:
    if not REMOTE_NAME_RE.fullmatch(host):
        raise PrivateStateSyncError("remote must be an SSH alias or host without shell syntax")
    if ssh_hostname is not None and not REMOTE_NAME_RE.fullmatch(ssh_hostname):
        raise PrivateStateSyncError("SSH hostname override contains unsafe syntax")
    if host_key_alias is not None and not REMOTE_NAME_RE.fullmatch(host_key_alias):
        raise PrivateStateSyncError("SSH host-key alias contains unsafe syntax")
    if host_key_alias is not None and ssh_hostname is None:
        raise PrivateStateSyncError("SSH host-key alias requires --ssh-hostname")
    if not REMOTE_PATH_RE.fullmatch(root) or ".." in PurePosixPath(root).parts:
        raise PrivateStateSyncError("remote vault root must be a safe absolute path")


def _ssh_options(
    *,
    ssh_hostname: str | None,
    host_key_alias: str | None,
) -> tuple[str, ...]:
    options = list(SSH_OPTIONS)
    if ssh_hostname is not None:
        options.extend(("-o", f"Hostname={ssh_hostname}"))
    if host_key_alias is not None:
        options.extend(("-o", f"HostKeyAlias={host_key_alias}"))
    return tuple(options)


def _remote_request(
    host: str,
    root: str,
    action: str,
    *,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
    **values: object,
) -> dict[str, Any]:
    _validate_remote(
        host,
        root,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    request = {"action": action, "root": root, **values}
    encoded_helper = base64.b64encode(REMOTE_HELPER.encode("utf-8")).decode("ascii")
    remote_program = (
        "import base64;exec(base64.b64decode(" + repr(encoded_helper) + "))"
    )
    result = subprocess.run(
        [
            "ssh",
            *_ssh_options(
                ssh_hostname=ssh_hostname,
                host_key_alias=host_key_alias,
            ),
            host,
            f"python3 -c {shlex.quote(remote_program)}",
        ],
        input=_canonical_json(request) + "\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "remote command failed"
        raise PrivateStateSyncError(f"remote operation failed: {detail}")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PrivateStateSyncError("remote operation returned invalid audit output") from exc
    if not isinstance(document, dict):
        raise PrivateStateSyncError("remote operation returned an invalid result")
    return document


def _inventory_from_document(document: Mapping[str, Any]) -> VaultInventory:
    try:
        fingerprint = str(document["fingerprint"])
        raw_files = document["files"]
        if not SHA256_RE.fullmatch(fingerprint) or not isinstance(raw_files, dict):
            raise ValueError
        files = {
            str(path): FileRecord(
                sha256=str(record["sha256"]),
                size=int(record["size"]),
            )
            for path, record in raw_files.items()
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise PrivateStateSyncError("remote inventory does not match the contract") from exc
    if any(not SHA256_RE.fullmatch(record.sha256) or record.size < 0 for record in files.values()):
        raise PrivateStateSyncError("remote inventory contains invalid file metadata")
    if any(
        not path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\n" in path
        or "\r" in path
        for path in files
    ):
        raise PrivateStateSyncError("remote inventory contains an unsafe path")
    expected = _digest(
        {
            path: {"sha256": record.sha256, "size": record.size}
            for path, record in sorted(files.items())
        }
    )
    if expected != fingerprint:
        raise PrivateStateSyncError("remote inventory fingerprint mismatch")
    return VaultInventory(files=files, fingerprint=fingerprint)


def inspect_remote_vault(
    host: str,
    root: str,
    *,
    allowed_lock_id: str | None = None,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> VaultInventory:
    document = _remote_request(
        host,
        root,
        "inventory",
        allowed_lock_id=allowed_lock_id,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    return _inventory_from_document(document)


def build_sync_plan(
    *,
    direction: str,
    remote: str,
    source: VaultInventory,
    target: VaultInventory,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> SyncPlan:
    if direction not in {"push", "pull"}:
        raise PrivateStateSyncError("direction must be push or pull")
    source_database = source.database
    if source_database is None:
        raise PrivateStateSyncError("source vault has no operational OneJournal database")

    source_immutable = {
        path: record
        for path, record in source.files.items()
        if path != DATABASE_RELATIVE_PATH
    }
    target_immutable = {
        path: record
        for path, record in target.files.items()
        if path != DATABASE_RELATIVE_PATH
    }
    shared = set(source_immutable) & set(target_immutable)
    conflicts = tuple(
        sorted(
            path
            for path in shared
            if source_immutable[path] != target_immutable[path]
        )
    )
    additions = tuple(sorted(set(source_immutable) - set(target_immutable)))
    target_only = tuple(sorted(set(target_immutable) - set(source_immutable)))
    source_label = "local" if direction == "push" else f"remote:{remote}"
    target_label = f"remote:{remote}" if direction == "push" else "local"
    body = {
        "contract_version": CONTRACT_VERSION,
        "operator_sha256": _file_sha256(Path(__file__).resolve()),
        "connection_sha256": _digest(
            {
                "remote": remote,
                "ssh_hostname": ssh_hostname,
                "host_key_alias": host_key_alias,
            }
        ),
        "direction": direction,
        "source_label": source_label,
        "target_label": target_label,
        "source_fingerprint": source.fingerprint,
        "target_fingerprint": target.fingerprint,
        "immutable_additions": additions,
        "target_only_files": target_only,
        "conflicts": conflicts,
        "source_database_sha256": source_database.sha256,
        "target_database_sha256": (
            target.database.sha256 if target.database is not None else None
        ),
    }
    return SyncPlan(**body, plan_fingerprint=_digest(body))


def _plan_document(plan: SyncPlan) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "operation": "plan",
        "direction": plan.direction,
        "source": plan.source_label,
        "target": plan.target_label,
        "plan_fingerprint": plan.plan_fingerprint,
        "immutable_addition_count": len(plan.immutable_additions),
        "target_only_preserved_count": len(plan.target_only_files),
        "immutable_conflict_count": len(plan.conflicts),
        "database_transfer_required": (
            plan.source_database_sha256 != plan.target_database_sha256
        ),
        "status": "ready" if not plan.conflicts else "blocked_conflict",
    }


def _acquire_local_lock(root: Path, transfer_id: str) -> None:
    lock_root = root / LOCK_DIRECTORY_NAME
    lock_root.mkdir(mode=0o700)
    owner = lock_root / "owner.json"
    owner.write_text(_canonical_json({"transfer_id": transfer_id}), encoding="utf-8")
    owner.chmod(0o600)


def _validate_lock(lock_root: Path, transfer_id: str) -> None:
    owner = lock_root / "owner.json"
    if (
        lock_root.is_symlink()
        or not lock_root.is_dir()
        or _mode(lock_root) != 0o700
        or owner.is_symlink()
        or not owner.is_file()
        or _mode(owner) != 0o600
    ):
        raise PrivateStateSyncError("local transfer lock is invalid")
    try:
        document = json.loads(owner.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PrivateStateSyncError("local transfer lock is invalid") from exc
    if document != {"transfer_id": transfer_id}:
        raise PrivateStateSyncError("local transfer lock belongs to another operation")


def _release_local_lock(root: Path, transfer_id: str) -> None:
    lock_root = root / LOCK_DIRECTORY_NAME
    _validate_lock(lock_root, transfer_id)
    (lock_root / "owner.json").unlink()
    lock_root.rmdir()


def _prepare_local_incoming(
    root: Path,
    transfer_id: str,
    expected_target_sha: str | None,
) -> Path:
    _validate_lock(root / LOCK_DIRECTORY_NAME, transfer_id)
    journal = root / "journal"
    if journal.exists():
        if journal.is_symlink() or not journal.is_dir() or _mode(journal) != 0o700:
            raise PrivateStateSyncError("journal directory must be non-symlink mode 0700")
    else:
        journal.mkdir(mode=0o700)
    current = root / DATABASE_RELATIVE_PATH
    if _open_handle_count(current):
        raise PrivateStateSyncError("destination database has an open handle")
    if Path(str(current) + ".wal").exists():
        raise PrivateStateSyncError("destination database WAL exists")
    actual = _file_sha256(current) if current.exists() else None
    if actual != expected_target_sha:
        raise PrivateStateSyncError("destination database changed after planning")
    incoming = journal / f".{current.name}.incoming-{transfer_id}"
    if incoming.exists() or incoming.is_symlink():
        raise PrivateStateSyncError("destination staging file already exists")
    return incoming


def _finalize_local_database(
    root: Path,
    *,
    transfer_id: str,
    expected_source_sha: str,
    expected_target_sha: str | None,
    stamp: str,
) -> bool:
    _validate_lock(root / LOCK_DIRECTORY_NAME, transfer_id)
    current = root / DATABASE_RELATIVE_PATH
    incoming = current.parent / f".{current.name}.incoming-{transfer_id}"
    if incoming.is_symlink() or not incoming.is_file() or _mode(incoming) != 0o600:
        raise PrivateStateSyncError("destination staging file is not private and regular")
    if _file_sha256(incoming) != expected_source_sha:
        raise PrivateStateSyncError("destination staging checksum mismatch")
    if _open_handle_count(current):
        raise PrivateStateSyncError("destination database acquired an open handle")
    actual = _file_sha256(current) if current.exists() else None
    if actual != expected_target_sha:
        raise PrivateStateSyncError("destination database changed before activation")
    backup_created = False
    if current.exists() and actual != expected_source_sha:
        backup_root = current.parent / "transfer-backups"
        if backup_root.exists():
            if (
                backup_root.is_symlink()
                or not backup_root.is_dir()
                or _mode(backup_root) != 0o700
            ):
                raise PrivateStateSyncError("transfer backup directory is invalid")
        else:
            backup_root.mkdir(mode=0o700)
        backup = backup_root / (
            f"onejournal-local-owner-v1.pre-transfer-{stamp}-{actual[:12]}.duckdb"
        )
        if backup.exists():
            raise PrivateStateSyncError("transfer backup target already exists")
        shutil.copy2(current, backup)
        backup.chmod(0o600)
        if _file_sha256(backup) != actual:
            raise PrivateStateSyncError("destination backup checksum mismatch")
        backup_created = True
    os.replace(incoming, current)
    current.chmod(0o600)
    if _file_sha256(current) != expected_source_sha:
        raise PrivateStateSyncError("activated destination database checksum mismatch")
    return backup_created


def _discard_local_incoming(root: Path, transfer_id: str) -> None:
    _validate_lock(root / LOCK_DIRECTORY_NAME, transfer_id)
    current = root / DATABASE_RELATIVE_PATH
    incoming = current.parent / f".{current.name}.incoming-{transfer_id}"
    if incoming.exists() and not incoming.is_symlink() and incoming.is_file():
        incoming.unlink()


def _secure_local_additions(
    root: Path,
    transfer_id: str,
    relative_paths: Sequence[str],
) -> None:
    _validate_lock(root / LOCK_DIRECTORY_NAME, transfer_id)
    for relative in relative_paths:
        relative_path = PurePosixPath(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or not relative_path.parts:
            raise PrivateStateSyncError("immutable addition contains an unsafe path")
        path = root.joinpath(*relative_path.parts)
        if path.is_symlink():
            raise PrivateStateSyncError("immutable addition is not a regular file")
        if not path.exists():
            continue
        if not path.is_file():
            raise PrivateStateSyncError("immutable addition is not a regular file")
        path.chmod(0o600)
        parent = path.parent
        while parent != root:
            if parent.is_symlink() or not parent.is_dir():
                raise PrivateStateSyncError(
                    "immutable addition parent is not a regular directory"
                )
            parent.chmod(0o700)
            parent = parent.parent


def _rsync(
    *,
    direction: str,
    remote: str,
    local_root: Path,
    remote_root: str,
    relative_paths: Sequence[str] | None = None,
    local_file: str | None = None,
    remote_file: str | None = None,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> None:
    _validate_remote(
        remote,
        remote_root,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    if remote_file is not None and (
        not REMOTE_PATH_RE.fullmatch(remote_file)
        or ".." in PurePosixPath(remote_file).parts
    ):
        raise PrivateStateSyncError("remote transfer file must be a safe absolute path")
    ssh_command = "ssh " + " ".join(
        _ssh_options(
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
    )
    command = [
        "rsync",
        "-a",
        "--checksum",
        "--timeout=120",
        "--rsync-path=umask 077 && rsync",
        "-e",
        ssh_command,
    ]
    input_text: str | None = None
    if relative_paths is not None:
        if not relative_paths:
            return
        command.extend(["--ignore-existing", "--files-from=-"])
        input_text = "".join(f"{path}\n" for path in relative_paths)
        local_endpoint = str(local_root) + "/"
        remote_endpoint = f"{remote}:{remote_root}/"
    else:
        if local_file is None or remote_file is None:
            raise PrivateStateSyncError("database transfer paths are required")
        local_endpoint = local_file
        remote_endpoint = f"{remote}:{remote_file}"
    if direction == "push":
        command.extend([local_endpoint, remote_endpoint])
    else:
        command.extend([remote_endpoint, local_endpoint])
    result = subprocess.run(
        command,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        umask=0o077,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "rsync failed"
        raise PrivateStateSyncError(f"private transfer failed: {detail}")


def _read_endpoints(
    *,
    direction: str,
    remote: str,
    local_root: Path,
    remote_root: str,
    allowed_lock_id: str | None = None,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> tuple[VaultInventory, VaultInventory]:
    local = inspect_local_vault(local_root, allowed_lock_id=allowed_lock_id)
    remote_inventory = inspect_remote_vault(
        remote,
        remote_root,
        allowed_lock_id=allowed_lock_id,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    return (local, remote_inventory) if direction == "push" else (remote_inventory, local)


def apply_sync_plan(
    *,
    expected_plan_fingerprint: str,
    direction: str,
    remote: str,
    local_root: Path,
    remote_root: str,
    ssh_hostname: str | None = None,
    host_key_alias: str | None = None,
) -> dict[str, object]:
    source, target = _read_endpoints(
        direction=direction,
        remote=remote,
        local_root=local_root,
        remote_root=remote_root,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    plan = build_sync_plan(
        direction=direction,
        remote=remote,
        source=source,
        target=target,
        ssh_hostname=ssh_hostname,
        host_key_alias=host_key_alias,
    )
    if plan.conflicts:
        raise PrivateStateSyncError("immutable same-path checksum conflict blocks transfer")
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise PrivateStateSyncError("plan fingerprint is stale or belongs to another handoff")

    transfer_id = plan.plan_fingerprint[:24]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    remote_locked = False
    local_locked = False
    incoming_prepared = False
    backup_created = False
    try:
        _remote_request(
            remote,
            remote_root,
            "acquire",
            transfer_id=transfer_id,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        remote_locked = True
        _acquire_local_lock(local_root, transfer_id)
        local_locked = True

        locked_source, locked_target = _read_endpoints(
            direction=direction,
            remote=remote,
            local_root=local_root,
            remote_root=remote_root,
            allowed_lock_id=transfer_id,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        locked_plan = build_sync_plan(
            direction=direction,
            remote=remote,
            source=locked_source,
            target=locked_target,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        if locked_plan.plan_fingerprint != plan.plan_fingerprint:
            raise PrivateStateSyncError("vault changed while transfer locks were acquired")

        _rsync(
            direction=direction,
            remote=remote,
            local_root=local_root,
            remote_root=remote_root,
            relative_paths=plan.immutable_additions,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        if direction == "push":
            _remote_request(
                remote,
                remote_root,
                "secure_additions",
                transfer_id=transfer_id,
                relative_paths=list(plan.immutable_additions),
                ssh_hostname=ssh_hostname,
                host_key_alias=host_key_alias,
            )
        else:
            _secure_local_additions(
                local_root,
                transfer_id,
                plan.immutable_additions,
            )

        if plan.source_database_sha256 != plan.target_database_sha256:
            if direction == "push":
                result = _remote_request(
                    remote,
                    remote_root,
                    "prepare_incoming",
                    transfer_id=transfer_id,
                    expected_target_sha=plan.target_database_sha256,
                    ssh_hostname=ssh_hostname,
                    host_key_alias=host_key_alias,
                )
                incoming_prepared = True
                incoming = str(result["incoming"])
                _rsync(
                    direction="push",
                    remote=remote,
                    local_root=local_root,
                    remote_root=remote_root,
                    local_file=str(local_root / DATABASE_RELATIVE_PATH),
                    remote_file=incoming,
                    ssh_hostname=ssh_hostname,
                    host_key_alias=host_key_alias,
                )
            else:
                incoming_path = _prepare_local_incoming(
                    local_root,
                    transfer_id,
                    plan.target_database_sha256,
                )
                incoming_prepared = True
                _rsync(
                    direction="pull",
                    remote=remote,
                    local_root=local_root,
                    remote_root=remote_root,
                    local_file=str(incoming_path),
                    remote_file=f"{remote_root}/{DATABASE_RELATIVE_PATH}",
                    ssh_hostname=ssh_hostname,
                    host_key_alias=host_key_alias,
                )

            frozen_source, _ = _read_endpoints(
                direction=direction,
                remote=remote,
                local_root=local_root,
                remote_root=remote_root,
                allowed_lock_id=transfer_id,
                ssh_hostname=ssh_hostname,
                host_key_alias=host_key_alias,
            )
            if (
                frozen_source.database is None
                or frozen_source.database.sha256 != plan.source_database_sha256
            ):
                raise PrivateStateSyncError("source database changed during transfer")

            if direction == "push":
                result = _remote_request(
                    remote,
                    remote_root,
                    "finalize",
                    transfer_id=transfer_id,
                    expected_source_sha=plan.source_database_sha256,
                    expected_target_sha=plan.target_database_sha256,
                    stamp=stamp,
                    ssh_hostname=ssh_hostname,
                    host_key_alias=host_key_alias,
                )
                backup_created = bool(result["backup_created"])
            else:
                backup_created = _finalize_local_database(
                    local_root,
                    transfer_id=transfer_id,
                    expected_source_sha=plan.source_database_sha256,
                    expected_target_sha=plan.target_database_sha256,
                    stamp=stamp,
                )
            incoming_prepared = False

        final_source, final_target = _read_endpoints(
            direction=direction,
            remote=remote,
            local_root=local_root,
            remote_root=remote_root,
            allowed_lock_id=transfer_id,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        final_plan = build_sync_plan(
            direction=direction,
            remote=remote,
            source=final_source,
            target=final_target,
            ssh_hostname=ssh_hostname,
            host_key_alias=host_key_alias,
        )
        if final_plan.conflicts or final_plan.immutable_additions:
            raise PrivateStateSyncError("post-transfer immutable verification failed")
        if final_plan.source_database_sha256 != final_plan.target_database_sha256:
            raise PrivateStateSyncError("post-transfer database verification failed")
        return {
            "contract_version": CONTRACT_VERSION,
            "operation": "apply",
            "direction": direction,
            "plan_fingerprint": plan.plan_fingerprint,
            "immutable_files_added": len(plan.immutable_additions),
            "target_only_files_preserved": len(final_plan.target_only_files),
            "database_transferred": (
                plan.source_database_sha256 != plan.target_database_sha256
            ),
            "destination_database_backup_created": backup_created,
            "status": "verified",
        }
    finally:
        if incoming_prepared:
            try:
                if direction == "push" and remote_locked:
                    _remote_request(
                        remote,
                        remote_root,
                        "discard",
                        transfer_id=transfer_id,
                        ssh_hostname=ssh_hostname,
                        host_key_alias=host_key_alias,
                    )
                elif direction == "pull" and local_locked:
                    _discard_local_incoming(local_root, transfer_id)
            except (OSError, PrivateStateSyncError, subprocess.SubprocessError):
                pass
        try:
            if local_locked:
                _release_local_lock(local_root, transfer_id)
        finally:
            if remote_locked:
                _remote_request(
                    remote,
                    remote_root,
                    "release",
                    transfer_id=transfer_id,
                    ssh_hostname=ssh_hostname,
                    host_key_alias=host_key_alias,
                )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply"))
    parser.add_argument("--direction", choices=("push", "pull"), required=True)
    parser.add_argument("--remote", required=True, help="SSH alias or host for the other Mac")
    parser.add_argument(
        "--ssh-hostname",
        help="Optional connection address overriding the SSH alias HostName",
    )
    parser.add_argument(
        "--host-key-alias",
        help="Existing trusted known_hosts identity used with --ssh-hostname",
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help=f"Local private vault (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--remote-root",
        default=str(DEFAULT_VAULT_ROOT),
        help=f"Remote private vault (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--plan-fingerprint",
        help="Exact fingerprint printed by a successful plan; required for apply",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.operation == "apply" and not args.plan_fingerprint:
            raise PrivateStateSyncError("apply requires --plan-fingerprint")
        if args.operation == "plan" and args.plan_fingerprint:
            raise PrivateStateSyncError("plan does not accept --plan-fingerprint")
        if args.operation == "plan":
            source, target = _read_endpoints(
                direction=args.direction,
                remote=args.remote,
                local_root=args.local_root,
                remote_root=args.remote_root,
                ssh_hostname=args.ssh_hostname,
                host_key_alias=args.host_key_alias,
            )
            plan = build_sync_plan(
                direction=args.direction,
                remote=args.remote,
                source=source,
                target=target,
                ssh_hostname=args.ssh_hostname,
                host_key_alias=args.host_key_alias,
            )
            document = _plan_document(plan)
            print(_canonical_json(document))
            return 0 if not plan.conflicts else 1
        result = apply_sync_plan(
            expected_plan_fingerprint=args.plan_fingerprint,
            direction=args.direction,
            remote=args.remote,
            local_root=args.local_root,
            remote_root=args.remote_root,
            ssh_hostname=args.ssh_hostname,
            host_key_alias=args.host_key_alias,
        )
        print(_canonical_json(result))
        return 0
    except (OSError, PrivateStateSyncError, subprocess.SubprocessError) as exc:
        print(f"OneJournal private handoff failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
