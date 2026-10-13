#!/usr/bin/env python3
"""Explicit operator-only empty hosted store setup/offline access recovery."""
import argparse
from pathlib import Path

from onejournal.hosted_site import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install-empty-journal", "provision-access", "recover-access"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--enrollment-file", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.action == "install-empty-journal":
            from onejournal.hosted_schema import install_empty
            install_empty(config.journal)
        else:
            from onejournal.hosted_access import provision
            if args.enrollment_file is None:
                raise ValueError("New enrollment file required.")
            provision(config.security, config.journal, config.origin,
                      args.enrollment_file, recover=args.action == "recover-access")
    except Exception:
        print("Hosted setup/recovery refused. Check the private binding, stopped service and new empty target; private values were not logged.")
        return 1
    print("Explicit hosted operation completed. No private journal import, deployment or service restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
