"""Mac-native encrypted recovery of an unaccepted activity report package.

No live configuration, security store, journal write, broker call or publication.
The image retains the exact preparation contract; restore only to temporary files.
"""
from contextlib import contextmanager
import getpass
import hmac
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

from onejournal.activity_report_preparation import verify_preparation, _copy_files
from onejournal.mac_access_backup import disk_image, password_bytes, validate_destination, private_output


def _outside_git(path):
    if any((parent/'.git').exists() for parent in (path.resolve(), *path.resolve().parents)):
        raise ValueError('Keep private packages, images and receipts outside Git.')


@contextmanager
def restored_backup(image, password, expected=None):
    """Verify encrypted bytes and regenerate every financial payload privately."""
    password_bytes(password)
    _outside_git(image)
    if not image.is_absolute() or image.is_symlink() or not image.is_file():
        raise ValueError('Choose an existing encrypted draft image.')
    if plistlib.loads(disk_image(['isencrypted', str(image), '-plist'])).get('encrypted') is not True:
        raise ValueError('The draft recovery image is not encrypted.')
    disk_image(['verify', str(image), '-stdinpass', '-quiet'], password)
    with tempfile.TemporaryDirectory(prefix='onejournal-draft-restore-', dir='/private/tmp') as folder:
        root = Path(folder)
        mount, restored = root/'mounted', root/'restored'
        mount.mkdir(mode=0o700)
        restored.mkdir(mode=0o700)
        attached = False
        try:
            disk_image(['attach', str(image), '-readonly', '-noautoopen', '-nobrowse',
                        '-mountpoint', str(mount), '-stdinpass', '-quiet'], password)
            attached = True
            # Full validation before copying rejects unsafe paths, extra files,
            # altered bytes and invented acceptance in an existing image too.
            package = mount/'package'
            manifest = verify_preparation(package)
            if expected is not None and manifest != expected:
                raise ValueError('Draft recovery image differs from the selected package.')
            _copy_files(package, restored, set(manifest['sha256']) | {'manifest.json'})
            if verify_preparation(restored) != manifest:
                raise ValueError('Restored draft differs from its encrypted image.')
            yield restored, manifest
        finally:
            if attached:
                disk_image(['detach', str(mount), '-quiet'])


def verify_backup(image, password, expected=None):
    with restored_backup(image, password, expected) as (_, manifest):
        return manifest


def create_backup(package, destination, password, *, require_usb=True):
    password_bytes(password)
    _outside_git(package)
    _outside_git(destination)
    validate_destination(destination, require_usb=require_usb)
    manifest = verify_preparation(package)
    names = set(manifest['sha256']) | {'manifest.json'}
    with tempfile.TemporaryDirectory(prefix='onejournal-draft-backup-', dir='/private/tmp') as folder:
        root = Path(folder)
        mount = root/'mounted'
        mount.mkdir(mode=0o700)
        working, image = root/'working.dmg', root/'encrypted.dmg'
        size = math.ceil(sum((package/name).stat().st_size for name in names)/1048576) + 32
        # Reuse the proven native blank-image/populate/encrypted-conversion flow.
        # Plaintext is confined to this local owner-only temporary directory.
        disk_image(['create', str(working), '-size', f'{size}m', '-fs', 'HFS+',
                    '-volname', 'OneJournal draft recovery', '-quiet'])
        attached = False
        try:
            disk_image(['attach', str(working), '-noautoopen', '-nobrowse',
                        '-mountpoint', str(mount), '-quiet'])
            attached = True
            mount.chmod(0o700)
            captured = mount/'package'
            captured.mkdir(mode=0o700)
            _copy_files(package, captured, names)
            if verify_preparation(captured) != manifest or verify_preparation(package) != manifest:
                raise ValueError('Draft changed during recovery capture.')
        finally:
            if attached:
                disk_image(['detach', str(mount), '-quiet'])
        disk_image(['convert', str(working), '-o', str(image), '-format', 'UDZO',
                    '-encryption', 'AES-256', '-stdinpass', '-quiet'], password)
        # Reserve only a new file. Never overwrite an earlier recovery image.
        validate_destination(destination, require_usb=require_usb)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output, image.open('rb') as original:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            return verify_backup(destination, password, manifest)
        except BaseException:
            destination.unlink(missing_ok=True)  # Only our new, unverified output.
            raise


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('--package', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'darwin' or not sys.stdin.isatty():
            raise ValueError('Use your own Mac Terminal for hidden password entry.')
        _outside_git(args.destination)
        if args.receipt:
            _outside_git(args.receipt)
            from onejournal.mac_evidence_audit_backup import _private_directory
            _private_directory(args.receipt.parent, 'receipt parent')
            if not args.receipt.is_absolute() or args.receipt.exists() or args.receipt.is_symlink():
                raise ValueError('Choose a new private receipt.')
        if args.action == 'create':
            if args.package is None:
                raise ValueError('Select the exact prepared package.')
            _outside_git(args.package)
            validate_destination(args.destination)
            verify_preparation(args.package)  # Fail before requesting a password.
        elif args.package is not None:
            raise ValueError('Verification needs only the encrypted image.')
        print('Draft recovery only. Existing images and the live site stay unchanged. Keep this password separately from the USB.', flush=True)
        password = getpass.getpass('Draft image password (20+ characters; hidden): ')
        password_bytes(password)
        if args.action == 'create':
            again = getpass.getpass('Enter the same password again: ')
            if not hmac.compare_digest(password.encode(), again.encode()):
                raise ValueError('Passwords do not match.')
            manifest = create_backup(args.package, args.destination, password)
        else:
            manifest = verify_backup(args.destination, password)
        result = dict(status='encrypted_draft_recovery_verified',
                      file_count=len(manifest['sha256']), package_fingerprint=manifest['package_fingerprint'],
                      publication_authorized=False)
        if args.receipt:
            private_output(args.receipt, (json.dumps(result, sort_keys=True)+'\n').encode())
        print(f"Encrypted draft backup verified: USB unlock, {result['file_count']} exact files and reproduced report/CSV/Trades. No live publication or broker request.")
        return 0
    except (Exception, KeyboardInterrupt):
        print('Draft backup did not complete. Check the private password, package, USB and free space. Existing images/live state are unchanged; private values were not logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
