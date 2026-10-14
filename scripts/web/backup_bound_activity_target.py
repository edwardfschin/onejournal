#!/usr/bin/env python3
"""Private Terminal password entry for an already read-only-bound journal backup."""
import argparse
import getpass
import hmac
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from onejournal.activity_live_binding import backup_bound_target,verify_bound_target,new_private_output
from onejournal.mac_access_backup import password_bytes,validate_destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binding','web-config','destination','receipt'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if sys.platform!='darwin' or not sys.stdin.isatty():
            raise ValueError('Use your own Mac Terminal for private password entry.')
        verify_bound_target(args.binding,args.web_config,ROOT)
        validate_destination(args.destination)
        new_private_output(args.receipt)
        print('Bound live-journal backup only. No migration, publication, broker access or restart. Earlier images stay untouched.',flush=True)
        password=getpass.getpass('New journal image password (20+ characters; hidden): ')
        password_bytes(password)
        again=getpass.getpass('Enter the same password again: ')
        if not hmac.compare_digest(password.encode(),again.encode()):
            print('Passwords did not match. No new backup was created.',file=sys.stderr)
            return 1
        result=backup_bound_target(binding_path=args.binding,config_path=args.web_config,project_root=ROOT,
            destination=args.destination,password=password,receipt_path=args.receipt)
        print(f"Fresh bound backup verified: USB restoration, {result['relation_count']} tables/views and unchanged live target. No publication or migration.")
        return 0
    except (Exception,KeyboardInterrupt):
        print('Bound backup did not complete. Check the private password, USB and target binding. Any verified image is retained; live data/site and earlier images were not changed.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
