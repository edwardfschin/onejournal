#!/usr/bin/env python3
"""Create, verify or rehearse the bounded encrypted Mac journal backup."""
import argparse
import getpass
import hmac
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from onejournal.mac_journal_backup import create_backup, verify_backup
from onejournal.mac_access_backup import password_bytes, validate_destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify", "rehearse"])
    parser.add_argument("--web-config", type=Path, default=Path.home() / ".onejournal/passkey-access/local-web.json")
    parser.add_argument("--destination", type=Path, help="A new/existing encrypted .dmg outside Git, on the mounted USB for creation.")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise ValueError("This command requires macOS built-in disk-image tools.")
        if args.web_config.resolve().is_relative_to(ROOT) or (args.destination and args.destination.resolve().is_relative_to(ROOT)):
            raise ValueError("Keep all financial setup and backup images outside Git.")
        if args.action == "rehearse":
            if args.destination is not None:
                raise ValueError("Rehearsal uses temporary local files only; omit --destination.")
            with tempfile.TemporaryDirectory(prefix="onejournal-journal-rehearsal-") as folder:
                count = create_backup(args.web_config, Path(folder).resolve() / "disposable.dmg", secrets.token_urlsafe(32), ROOT, require_usb=False)
            print(f"Encrypted journal rehearsal passed: exact files, {count} tables/views, schema and release validation. Temporary files removed; no live write or restart.")
            return 0
        if args.destination is None:
            raise ValueError("Choose the exact recovery image with --destination.")
        if not sys.stdin.isatty():
            raise ValueError("Run this in your own Terminal; enter the image password privately.")
        if args.action == "create":
            validate_destination(args.destination)
        print("Journal/release backup only. Existing access image is preserved. Keep the password separately. No live overwrite, checkpoint or service restart.", flush=True)
        password = getpass.getpass("Journal image password (20+ characters; input is hidden): ")
        password_bytes(password)
        if args.action == "create":
            again = getpass.getpass("Enter the same password again: ")
            if not hmac.compare_digest(password.encode(), again.encode()):
                raise ValueError("Passwords did not match; nothing was backed up.")
            count = create_backup(args.web_config, args.destination, password, ROOT)
        else:
            count = verify_backup(args.destination, password, ROOT)
        print(f"Encrypted journal backup verified: USB unlock, exact files, {count} tables/views, schema and release validation passed. No live write or restart.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Cancelled. No live write or service restart.", file=sys.stderr)
    except ValueError as error:
        # Parsing errors may contain private data. Show only our fixed messages.
        if type(error) is ValueError:
            print(f"Journal backup did not complete: {error}", file=sys.stderr)
        else:
            print("Journal backup did not complete. Private validation details were not logged.", file=sys.stderr)
    except Exception:
        print("Journal backup did not complete. Check private setup, database availability, USB and space. Private details were not logged.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
