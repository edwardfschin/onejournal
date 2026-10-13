#!/usr/bin/env python3
"""Encrypted hosted journal/access backup or new-empty-target recovery; never activates services."""
import argparse
import getpass
import json
from pathlib import Path

from onejournal.hosted_backup import create, restore
from onejournal.hosted_site import load_config
from onejournal.local_web import private_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--companion-directory", type=Path)
    parser.add_argument("--password-file", type=Path,
                        help="Owner-only operator file for a separately activated backup timer; never put passwords in arguments.")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        password = private_file(args.password_file, "backup password", private_parent=True).read_text().rstrip("\n") if args.password_file else getpass.getpass("Backup password (hidden; 20+ characters): ")
        if args.action == "create":
            if not args.password_file and password != getpass.getpass("Enter the same password again: "):
                raise ValueError("Passwords differ.")
            doc = json.loads(args.config.read_text())
            files = {"hosted-config.json": args.config}
            files.update({name + ".private": Path(doc[name]) for name in
                          ("journal_dsn_file", "security_dsn_file", "proxy_secret_file", "broker_authorization", "reporting_authorization") if doc[name] is not None})
            create(config.journal, config.security, args.image, password, private_files=files)
            print("Encrypted hosted backup created. Keep an off-server copy and password separately; restore verification is still required.")
        else:
            if args.companion_directory is None:
                raise ValueError("New private companion directory required.")
            restore(config.journal, config.security, args.image, password, args.companion_directory)
            print("Exact hosted restoration passed in two empty targets. No service activation, credential enrollment or live overwrite.")
    except Exception:
        print("Hosted backup/recovery did not complete. Check the stopped service, private files, password, PostgreSQL tools and new empty targets. Private values were not logged.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
