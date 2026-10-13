#!/usr/bin/env python3
"""Temporary-copy journal migration rehearsal only; no live-target capability."""
import argparse
import json
import os
from pathlib import Path

from onejournal.hosted_migration import rehearse, _temporary_private_directory
from onejournal.journal.storage import PostgresTarget
from onejournal.local_web import private_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-copy', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--target-dsn-file', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    created = False
    try:
        _temporary_private_directory(args.receipt.parent)
        fd = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(fd, 'w') as output:
            dsn = private_file(args.target_dsn_file, 'rehearsal target', private_parent=True).read_text().strip()
            result = rehearse(args.source_copy, args.source_sha256, PostgresTarget(dsn))
            json.dump(result, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        if created:
            args.receipt.unlink(missing_ok=True)  # Our new failed receipt only.
        print('Migration rehearsal refused. Check the frozen hash, pinned 0028 schema, empty temporary target and private files. No activation or live repair was attempted.')
        return 1
    print('Guarded journal migration rehearsal passed: exact tables/views and unchanged source. No activation, history extension or service change.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
