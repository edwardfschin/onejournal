#!/usr/bin/env python3
"""Create/verify an encrypted access-setup USB image; never touch journal/runtime."""
import argparse
import getpass
import hmac
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from onejournal.mac_access_backup import create_backup, password_bytes, validate_destination, verify_backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("--source-dir", type=Path, default=Path.home() / ".onejournal/passkey-access")
    parser.add_argument("--destination", required=True, type=Path, help="New/existing encrypted .dmg on the approved mounted USB.")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise ValueError("This operator command requires macOS built-in disk-image tools.")
        if not sys.stdin.isatty():
            raise ValueError("Run this command in your own Terminal; the password must be entered privately.")
        if args.source_dir.resolve().is_relative_to(ROOT) or args.destination.resolve().is_relative_to(ROOT):
            raise ValueError("Keep access setup and backup images outside Git.")
        if args.action == "create":
            validate_destination(args.destination)
        print("This backs up access setup only, not your journal or passkey. Keep the password separately from the USB. Nothing is erased or restarted.", flush=True)
        password = getpass.getpass("Recovery image password (20+ characters; input is hidden): ")
        password_bytes(password)
        if args.action == "create":
            again = getpass.getpass("Enter the same password again: ")
            if not hmac.compare_digest(password.encode(), again.encode()):
                raise ValueError("Passwords did not match; nothing was backed up.")
            create_backup(args.source_dir, args.destination, password)
        else:
            verify_backup(args.destination, password)
        print("Encrypted access backup verified: USB unlock and disposable file restoration passed. No journal change or service restart.", flush=True)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Cancelled. No journal change or service restart.", file=sys.stderr)
    except ValueError as error:
        print(f"Backup did not complete: {error}", file=sys.stderr)
    except Exception:
        print("Backup did not complete. Check private source files, the mounted USB and available space. Private details were not logged.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
