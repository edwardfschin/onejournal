#!/usr/bin/env python3
"""Import historical activity only into a new disposable copy; never a live DB."""
import argparse
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onejournal.journal.historical_activity_rehearsal import rehearse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--source-db-sha256', required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--bundle-fingerprint', required=True)
    parser.add_argument('--rehearsal-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rehearse(source_db=args.source_db, source_db_sha256=args.source_db_sha256,
                 bundle_path=args.bundle, expected_bundle_fingerprint=args.bundle_fingerprint,
                 output_dir=args.rehearsal_dir)
    except Exception:
        # Native database/OS/parser messages can include account data or paths.
        print('Historical rehearsal stopped. Check the exact private inputs, permissions, source checksum and new output directory.', file=sys.stderr)
        return 1
    print('Historical copy import verified: exact replay and prior history preserved. No live write, financial publication or restart.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
