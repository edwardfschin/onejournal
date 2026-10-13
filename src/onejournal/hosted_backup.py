"""Encrypted, authenticated PostgreSQL backups and fresh-target-only restore.

No service control, deployment, broker access or live overwrite. Stop the
OneJournal worker first; its durable access lease enforces that boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from psycopg.conninfo import conninfo_to_dict

from onejournal.hosted_access import LEASE
from onejournal.hosted_schema import validate
from onejournal.journal.storage import PostgresTarget, connect
from onejournal.local_web import private_file

MAGIC = b"ONJPG01\0"
CHUNK = 1024 * 1024


def _file_hash(path):
    checksum = sha256()
    with path.open("rb") as source:
        while block := source.read(CHUNK):
            checksum.update(block)
    return checksum.hexdigest()


def _key(password: str, salt: bytes):
    if not isinstance(password, str) or not 20 <= len(password) <= 1024:
        raise ValueError("Use a separate unique backup password of at least 20 characters.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def encrypt(source: Path, destination: Path, password: str):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    enc = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce)).encryptor()
    enc.authenticate_additional_data(header)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            output.write(header)
            while block := input_file.read(CHUNK):
                output.write(enc.update(block))
            output.write(enc.finalize())
            output.write(enc.tag)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        destination.unlink(missing_ok=True)  # Only our newly reserved output.
        raise


def decrypt(source: Path, destination: Path, password: str):
    size = source.stat().st_size
    if size < 52 or size > 8 * 1024**3:
        raise ValueError("Backup size is unsupported.")
    with source.open("rb") as input_file:
        header = input_file.read(36)
        if header[:8] != MAGIC:
            raise ValueError("Backup contract is invalid.")
        input_file.seek(-16, os.SEEK_END)
        tag = input_file.read(16)
        input_file.seek(36)
        dec = Cipher(algorithms.AES(_key(password, header[8:24])), modes.GCM(header[24:36], tag)).decryptor()
        dec.authenticate_additional_data(header)
        remaining = size - 52
        created = False
        try:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            created = True
            with os.fdopen(fd, "wb") as output:
                while remaining:
                    block = input_file.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError("Backup is truncated.")
                    output.write(dec.update(block))
                    remaining -= len(block)
                output.write(dec.finalize())  # Authentication before any restore.
        except Exception:
            if created:
                destination.unlink(missing_ok=True)
            raise


def _binary(name, binary_directory: Path | None):
    candidate = str(binary_directory / name) if binary_directory else shutil.which(name)
    if candidate is None or not Path(candidate).is_file():
        raise ValueError("Install matching PostgreSQL dump/restore tools first.")
    return candidate


def _pg_run(name, target, args, folder, binary_directory):
    values = conninfo_to_dict(target.dsn)
    # Do not put a DSN/password on the command line or inherit external PG
    # connection overrides. A temporary owner-only passfile is used if needed.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    for key, env_name in {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER", "dbname": "PGDATABASE"}.items():
        if key in values:
            environment[env_name] = values[key]
    environment["PGCONNECT_TIMEOUT"] = "5"
    if values.get("password"):
        passfile = folder / ("pass-" + secrets.token_hex(8))
        def escape(value):
            return value.replace("\\", "\\\\").replace(":", "\\:")
        with passfile.open("x", encoding="utf-8") as output:
            passfile.chmod(0o600)
            output.write(":".join(escape(values.get(k, "*")) for k in ["host", "port", "dbname", "user", "password"]) + "\n")
        environment["PGPASSFILE"] = str(passfile)
    else:
        environment["PGPASSFILE"] = str(folder / "absent-passfile")
    subprocess.run([_binary(name, binary_directory), *args], env=environment,
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)


def relation_manifest(target):
    """Private exact content evidence, held only inside the encrypted backup."""
    with connect(target, read_only=True) as con:
        names = [row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()]
        result = {}
        for name in names:
            # Only catalog identifiers, not HTTP/user SQL. These schemas contain
            # sortable scalar columns (including explicit text JSON), not jsonb.
            columns = [row[0] for row in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position", [name]).fetchall()]
            quote = lambda value: '"' + value.replace('"', '""') + '"'
            query = f"SELECT * FROM main.{quote(name)} ORDER BY " + ','.join(quote(value) for value in columns)
            cursor = con.connection.cursor()
            cursor.execute(query)
            count, checksum = 0, sha256()
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    checksum.update((json.dumps(row, default=lambda v: v.hex() if isinstance(v, bytes) else str(v), separators=(',', ':')) + '\n').encode())
                    count += 1
            result[name] = {"columns": columns, "rows": count, "sha256": checksum.hexdigest()}
        return result


@contextmanager
def _stopped_security(target):
    with connect(target) as con:
        if not con.execute("SELECT pg_try_advisory_lock(?)", [LEASE]).fetchone()[0]:
            raise ValueError("Stop the protected hosted service before backup/recovery.")
        yield


def create(journal, security, destination, password, *, private_files=None, binary_directory=None):
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError("Use a new absolute encrypted backup destination.")
    private_files = private_files or {}
    if any(Path(name).name != name or name in {"journal.dump", "access.dump", "manifest.json", "bundle.tar"} for name in private_files):
        raise ValueError("Backup companion names are invalid.")
    with tempfile.TemporaryDirectory(prefix="onejournal-hosted-backup-") as tmp:
        root = Path(tmp)
        root.chmod(0o700)
        with _stopped_security(security), connect(journal):
            validate(journal)
            manifests = {"journal": relation_manifest(journal), "access": relation_manifest(security)}
            for name, target in [("journal.dump", journal), ("access.dump", security)]:
                _pg_run("pg_dump", target, ["--format=custom", "--no-owner", "--no-acl", "--file=" + str(root / name)], root, binary_directory)
                (root / name).chmod(0o600)
            for name, source in private_files.items():
                shutil.copyfile(private_file(source, "backup companion", private_parent=True), root / name)
                (root / name).chmod(0o600)
            contents = ["journal.dump", "access.dump", *private_files]
            file_hashes = {name: _file_hash(root / name) for name in contents}
            (root / "manifest.json").write_text(json.dumps({"contract_version": "onejournal.hosted-backup.v1", "relations": manifests, "files": file_hashes}, sort_keys=True))
        bundle = root / "bundle.tar"
        with tarfile.open(bundle, "w") as archive:
            for name in ["manifest.json", *contents]:
                archive.add(root / name, arcname=name, recursive=False)
        encrypt(bundle, destination, password)


def restore(journal, security, source, password, companion_directory, *, binary_directory=None):
    private_file(source, "encrypted backup")
    if companion_directory.exists() or not companion_directory.is_absolute():
        raise ValueError("Use a new absolute private companion directory.")
    with tempfile.TemporaryDirectory(prefix="onejournal-hosted-restore-") as tmp:
        root = Path(tmp)
        decrypt(source, root / "bundle.tar", password)
        with tarfile.open(root / "bundle.tar") as archive:
            entries = archive.getmembers()
            if len(entries) > 16 or any(not entry.isfile() or Path(entry.name).name != entry.name or entry.size > 8*1024**3 for entry in entries):
                raise ValueError("Backup archive layout is invalid.")
            if len({entry.name for entry in entries}) != len(entries):
                raise ValueError("Backup archive contains duplicate files.")
            archive.extractall(root, filter="data")
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["contract_version"] != "onejournal.hosted-backup.v1" or set(manifest["files"]) | {"manifest.json"} != {entry.name for entry in entries}:
            raise ValueError("Backup manifest is incompatible.")
        for name, checksum in manifest["files"].items():
            if _file_hash(root / name) != checksum:
                raise ValueError("Backup file verification failed.")
        # Authenticate and inspect BOTH targets before any database restore.
        for target in (journal, security):
            with connect(target) as con:
                if con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')").fetchone()[0]:
                    raise ValueError("Restore requires two new empty databases; live overwrite is forbidden.")
        for name, target, group in [("journal.dump", journal, "journal"), ("access.dump", security, "access")]:
            _pg_run("pg_restore", target, ["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--dbname=" + conninfo_to_dict(target.dsn)["dbname"], str(root / name)], root, binary_directory)
            if relation_manifest(target) != manifest["relations"][group]:
                raise ValueError("Restored relations do not exactly match the encrypted manifest.")
        validate(journal)
        companion_directory.mkdir(mode=0o700)
        for name in manifest["files"]:
            if name not in {"journal.dump", "access.dump"}:
                shutil.copyfile(root / name, companion_directory / name)
                (companion_directory / name).chmod(0o600)
        # No startup, role grants, credentials reuse or live path selection.
        return {"restored": True, "exact_relations": True, "activated": False}
