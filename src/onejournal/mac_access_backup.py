"""Mac-native encrypted access-setup backup, never a passkey/journal backup."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import ssl
import subprocess
import tempfile

from onejournal.local_web import private_file

VERSION = "onejournal.mac-access-backup.v1"
FILES = ("local-web.json", "localhost-cert.pem", "localhost-key.pem", "OneJournal-localhost.cer")
README = """OneJournal Mac access recovery

This encrypted image preserves local access setup ONLY. It contains no journal,
broker credentials, passkey private keys, security database, sessions or enrollment
grants. Your existing journal and financial-release authorization files require
their own backups; this image cannot restore a lost financial database.

If the Mac still has its access setup but a passkey is lost:
1. Stop the protected website/API, using its owning terminal.
2. Use run_mac_passkey_prototype.py recover with the existing private config,
   security database and a NEW enrollment-file path. Privately confirm REPLACE
   PASSKEYS. This revokes ALL previous registrations and preserves security audit.
3. Start the protected service, use the fresh ten-minute grant privately to
   register a new passkey, then sign in. Never put a grant in a URL or chat.

If the access setup itself is lost:
1. Unlock this image privately. Restore its four setup files into a NEW local
   directory owned by you (0700), with files 0600. Do not overwrite existing files.
2. Review the config's private paths against the separately restored journal and
   exact release authorization files. Check the certificate is still valid and
   trusted for localhost SSL. Expired certificates require deliberate renewal.
3. With explicit owner authority and the service stopped, provision a NEW security
   database/grant. Never restore an older security database or revoked credentials.
4. Start, enroll and sign in. Fresh enrollment is required; this image is NOT a
   login bypass or an independent passkey. Local OS-owner authority is required.

Store the image password separately from this USB and the Mac-only copy. Losing
the password makes this image unusable. Do not save it in chat, scripts or Git.
Refresh this backup after changing local setup. Keep the USB disconnected/stored
safely after verification. This is Mac-only recovery, not VPS/production acceptance.
"""


def password_bytes(password: str) -> bytes:
    if not isinstance(password, str) or len(password) < 20 or any(ord(c) < 32 for c in password):
        raise ValueError("Use a unique recovery password of at least 20 characters; several unrelated words work well.")
    return password.encode("utf-8") + b"\0"


def disk_image(arguments: list[str], password: str | None = None) -> bytes:
    try:
        result = subprocess.run(["/usr/bin/hdiutil", *arguments],
            input=password_bytes(password) if password is not None else b"",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Disk-image operation failed. Check the password, free space and Mac disk-image permissions. Private details were not logged.") from None


def private_output(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def setup_snapshot(source: Path) -> dict[str, bytes]:
    contents = {}
    for name in FILES:
        path = private_file(source / name, "access backup source", private_parent=True)
        if path.stat().st_size > 65536:
            raise ValueError("Access setup file is unexpectedly large; nothing was backed up.")
        contents[name] = path.read_bytes()
    # Check the existing local certificate/key pair, without changing trust.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(source / "localhost-cert.pem", source / "localhost-key.pem")
        if ssl.PEM_cert_to_DER_cert(contents["localhost-cert.pem"].decode()) != contents["OneJournal-localhost.cer"]:
            raise ValueError
    except (OSError, ValueError, ssl.SSLError):
        raise ValueError("The access certificate files and private key do not match.") from None
    contents["RECOVERY.txt"] = README.encode()
    return contents


def hashes(contents: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}


def verify_backup(image: Path, password: str, expected: dict[str, str] | None = None) -> None:
    """Unlock read-only; restore only to disposable owner-private local files."""
    password_bytes(password)
    if plistlib.loads(disk_image(["isencrypted", str(image), "-plist"])).get("encrypted") is not True:
        raise ValueError("The recovery image is not encrypted.")
    disk_image(["verify", str(image), "-stdinpass", "-quiet"], password)
    with tempfile.TemporaryDirectory(prefix="onejournal-access-verify-") as folder:
        root = Path(folder).resolve()
        mount = root / "mounted"
        mount.mkdir(mode=0o700)
        attached = False
        try:
            disk_image(["attach", str(image), "-readonly", "-noautoopen", "-nobrowse",
                        "-mountpoint", str(mount), "-stdinpass", "-quiet"], password)
            attached = True
            manifest_path = mount / "manifest.json"
            if manifest_path.is_symlink() or manifest_path.stat().st_size > 65536:
                raise ValueError("The recovery manifest is invalid.")
            manifest = json.loads(manifest_path.read_bytes())
            allowed = {*FILES, "RECOVERY.txt"}
            if (manifest.get("contract_version") != VERSION or
                    not isinstance(manifest.get("sha256"), dict) or set(manifest["sha256"]) != allowed):
                raise ValueError("The recovery manifest has unsupported contents.")
            restored = root / "restored"
            restored.mkdir(mode=0o700)
            actual = {}
            for name in sorted(allowed):
                path = mount / name
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
                    raise ValueError("The recovery image has invalid setup files.")
                private_output(restored / name, path.read_bytes())
                actual[name] = hashlib.sha256((restored / name).read_bytes()).hexdigest()
            if actual != manifest["sha256"] or (expected is not None and actual != expected):
                raise ValueError("Restored access files do not match the recorded backup.")
            setup_snapshot(restored)
        finally:
            if attached:
                # Detach only our own temporary mount; never eject the USB.
                disk_image(["detach", str(mount), "-quiet"])


def validate_destination(destination: Path, *, require_usb: bool = True) -> None:
    if (not destination.is_absolute() or destination.suffix != ".dmg" or
            destination.exists() or destination.is_symlink() or
            not destination.parent.is_dir() or destination.parent.resolve() != destination.parent):
        raise ValueError("Choose a new .dmg file in an existing non-symlink destination folder. Nothing was overwritten.")
    if require_usb:
        parts = destination.parts
        if len(parts) < 4 or parts[1] != "Volumes" or not os.path.ismount(Path(*parts[:3])):
            raise ValueError("The USB volume is not mounted; nothing will be written to a substitute local folder.")


def create_backup(source: Path, destination: Path, password: str, *, require_usb: bool = True) -> None:
    password_bytes(password)
    validate_destination(destination, require_usb=require_usb)
    contents = setup_snapshot(source)
    expected = hashes(contents)
    with tempfile.TemporaryDirectory(prefix="onejournal-access-backup-") as folder:
        root = Path(folder).resolve()
        stage = root / "setup"
        stage.mkdir(mode=0o700)
        # Populated -srcfolder images fail with Resource busy on this Mac.
        # Use the native blank-image -> populate -> encrypted conversion flow.
        # The plaintext working image stays inside this local 0700 temporary dir.
        working = root / "working.dmg"
        disk_image(["create", str(working), "-size", "20m", "-fs", "HFS+",
                    "-volname", "OneJournal access recovery", "-quiet"])
        attached = False
        try:
            disk_image(["attach", str(working), "-noautoopen", "-nobrowse",
                        "-mountpoint", str(stage), "-quiet"])
            attached = True
            stage.chmod(0o700)
            for name, data in contents.items():
                private_output(stage / name, data)
            private_output(stage / "manifest.json", json.dumps({"contract_version": VERSION, "sha256": expected}, sort_keys=True).encode())
        finally:
            if attached:
                disk_image(["detach", str(stage), "-quiet"])
        image = root / "recovery.dmg"
        disk_image(["convert", str(working), "-o", str(image), "-format", "UDZO",
                    "-encryption", "AES-256", "-stdinpass", "-quiet"], password)
        verify_backup(image, password, expected)
        # Only the already-encrypted image goes to USB. Reserve without overwrite.
        validate_destination(destination, require_usb=require_usb)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output, image.open("rb") as original:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            # Re-read and restore the USB copy, not just the local staging image.
            verify_backup(destination, password, expected)
        except BaseException:
            destination.unlink(missing_ok=True)  # Our newly created incomplete output only.
            raise
