#!/usr/bin/env python3
"""Owner-operated, Mac-only encrypted source-evidence and audit recovery."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from onejournal.mac_evidence_audit_backup import create_backup, verify_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up only accepted source evidence and value-free security audit to an encrypted Mac USB image.")
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--web-config", type=Path, default=Path.home() / ".onejournal/passkey-access/local-web.json")
    parser.add_argument("--security-db", type=Path, default=Path.home() / ".onejournal/passkey-access/access.duckdb")
    parser.add_argument("--raw-root", type=Path, help="Private evidence directory outside Git; required for create.")
    parser.add_argument("--destination", type=Path, required=True, help="New image on a mounted USB for create; existing image for verify.")
    args = parser.parse_args(argv)
    if args.action == "create" and args.raw_root is None:
        parser.error("create requires --raw-root")
    print("Evidence/audit image only. Stop the protected local site first; no journal, passkey, live security or service change is made by this command.")
    print("The password is entered privately here, never into chat, and must be kept separately from the USB.")
    try:
        password = getpass.getpass("Evidence image password (20+ characters; input is hidden): ")
        if args.action == "create":
            confirm = getpass.getpass("Enter the same password again: ")
            if password != confirm:
                raise ValueError("Passwords did not match; nothing was backed up.")
            assert args.raw_root is not None
            files, events = create_backup(args.web_config, args.security_db, args.raw_root,
                                          args.destination, password, ROOT)
            print(f"Encrypted USB evidence backup verified by disposable restoration: {files} exact files, {events} value-free audit events. No live write or restart.")
        else:
            files, events = verify_backup(args.destination, password)
            print(f"Encrypted evidence backup unlocked and restored disposably: {files} exact files, {events} value-free audit events. No live write or restart.")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Evidence backup cancelled; no image was published.", file=sys.stderr)
        return 1
    except ValueError as exc:
        # Approved errors are generic and contain no paths, credentials or records.
        print(f"Evidence backup did not complete: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Evidence backup did not complete. Check private file permissions, free space and the stopped-site state; private details were not logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
