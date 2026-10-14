#!/usr/bin/env python3
"""Read-only check of an accepted draft, bound live target and verified USB image."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from onejournal.activity_live_binding import verify_publication_readiness


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binding','web-config','package','publication-dir','backup-receipt','backup-image'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        verify_publication_readiness(binding_path=args.binding,config_path=args.web_config,
            project_root=ROOT,package=args.package,publication_dir=args.publication_dir,
            backup_receipt_path=args.backup_receipt,backup_image=args.backup_image)
        print('Publication preparation ready: accepted draft, unchanged bound target and verified recovery image match. No publication, migration, broker access or restart.')
        return 0
    except (Exception,KeyboardInterrupt):
        print('Publication preparation is not ready. Check the selected draft, target binding and verified backup; changed evidence requires review, not an automatic rebind. No live state was changed.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
