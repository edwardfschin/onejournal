#!/usr/bin/env python3
"""Owner-operated disposable recovery of existing images; never replace live files."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from onejournal.local_web import parse_config, private_file
from onejournal.mac_access_backup import private_output, restored_backup as access_copy
from onejournal.mac_journal_backup import AUTH_FILES, file_hash, inventory, restored_backup as journal_copy
from onejournal.mac_evidence_audit_backup import source_digests, restored_backup as evidence_copy
from onejournal.mac_release_check import check_release
from onejournal.passkey_access import PREFIX, provision


def rebound_config(journal: Path, manifest: dict, port: int) -> Path:
    """Leave the exact original configuration intact; write a new copy-only binding."""
    document = json.loads((journal / 'local-web.json').read_bytes())
    document['journal_db_path'] = str(journal / 'journal.duckdb')
    for field, name in AUTH_FILES.items():
        if name in manifest['sha256']:
            document[field] = str(journal / name)
    document.update(web_port=port, api_port=port + 1, start_page='/local/reports')
    parse_config(document)
    path = journal / 'rehearsal-web.json'
    private_output(path, json.dumps(document, sort_keys=True).encode())
    return path


def probe(origin: str, cert: Path, grant: Path, index_hash: str) -> None:
    """Signed ephemeral test device, own cookie jar; no owner passkey or browser login."""
    import hashlib
    import httpx
    # Reuse the existing test wire-format device, not a production auth shortcut.
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_mac_passkey_access import SyntheticAuthenticator
    device = SyntheticAuthenticator()
    secret = grant.read_text().strip()
    context = ssl.create_default_context(cafile=str(cert))
    with httpx.Client(base_url=origin, verify=context, trust_env=False,
                      follow_redirects=False, timeout=5) as client:
        def post(name, value, headers=None):
            response = client.post(PREFIX + '/' + name, json=value,
                                   headers={'Origin': origin, **(headers or {})})
            if response.status_code != 200:
                raise ValueError('Restored access journey failed.')
            return response.json()
        shell = client.get('/local/reports')
        if shell.status_code != 200 or hashlib.sha256(shell.content).hexdigest() != index_hash:
            raise ValueError('Restored shell differs from the selected release.')
        path = '/api/v1/local-owner/reports/current/accounts'
        if client.get(path).status_code != 401:
            raise ValueError('Restored financial view is not locked.')
        options = post('register/options', {'enrollment_secret': secret})
        post('register/verify', {'enrollment_secret': secret, 'ceremony': options['ceremony'],
             'credential': device.credential(options['options'], register=True, origin=origin)})
        options = post('login/options', {})
        post('login/verify', {'ceremony': options['ceremony'],
             'credential': device.credential(options['options'], origin=origin)})
        state = client.get(PREFIX + '/session').json()
        if not state.get('authenticated') or not state.get('csrf'):
            raise ValueError('Restored session is unavailable.')
        accounts = client.get(path)
        symbols = client.get('/api/v1/local-owner/reports/current/symbols')
        exported = client.get('/api/v1/local-owner/reports/current/positions.csv')
        if any(response.status_code != 200 for response in (accounts, symbols, exported)):
            raise ValueError('Restored current-report journey failed.')
        fingerprint = accounts.json()['metadata']['report_release_fingerprint']
        if (symbols.json()['metadata']['report_release_fingerprint'] != fingerprint
                or exported.headers.get('X-OneJournal-Report-Release-Fingerprint') != fingerprint
                or not exported.headers.get('content-type', '').startswith('text/csv')):
            raise ValueError('Restored report and export releases differ.')
        post('logout', {}, {'X-OneJournal-CSRF': state['csrf']})
        if client.get(path).status_code != 401:
            raise ValueError('Restored logout did not lock financial access.')


def serve_and_probe(args, journal, setup, manifest, index_hash):
    """Start/stop only a new child against temporary restored paths on a free port."""
    import duckdb
    port = args.port
    if port == 4173 or not 1024 <= port < 65535:
        raise ValueError('Use a separate non-live local port.')
    with socket.socket() as check:
        check.bind(('127.0.0.1', port))
    config = rebound_config(journal, manifest, port)
    security = journal / 'rehearsal-access.duckdb'
    grant = journal / 'rehearsal-enrollment.txt'
    origin = f'https://localhost:{port}'
    if file_hash(setup / 'localhost-cert.pem') != args.tls_cert_sha256:
        raise ValueError('Recovered TLS differs from the accepted setup receipt.')
    provision(security, journal / 'journal.duckdb', origin, grant)
    command = [str(args.runtime_python), '-B', '-m', 'onejournal.mac_static_site',
               '--owner-local', '--web-config', str(config), '--security-db', str(security),
               '--tls-cert', str(setup / 'localhost-cert.pem'), '--tls-key', str(setup / 'localhost-key.pem'),
               '--static-dir', str(args.release_dir / 'static')]
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
    child = subprocess.Popen(command, cwd=journal, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while True:
            if child.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('Restored protected service did not start.')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    break
            except OSError:
                time.sleep(.1)
        probe(origin, setup / 'localhost-cert.pem', grant, index_hash)
        if child.poll() is not None:
            raise ValueError('Restored service stopped before verification completed.')
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    with duckdb.connect(str(journal / 'journal.duckdb'), read_only=True) as con:
        after = inventory(con)
    before = manifest['inventory']
    audit = 'phase1_reporting_api_audit_events'
    if (after['relations'] != before['relations'] or after['columns'] != before['columns']
            or {k:v for k,v in after['counts'].items() if k != audit} !=
               {k:v for k,v in before['counts'].items() if k != audit}
            or after['counts'][audit] != before['counts'][audit] + 3):
        raise ValueError('Unexpected restored journal changes; rehearsal did not pass.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('journal-image', 'access-image', 'evidence-image', 'runtime-python', 'release-dir', 'receipt'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('manifest-sha256', 'source-commit', 'tls-cert-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, default=4174)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if sys.platform != 'darwin' or not sys.stdin.isatty():
            raise ValueError('Run in your own Mac Terminal; enter passwords privately.')
        if args.port == 4173 or not 1024 <= args.port < 65535:
            raise ValueError('Use a separate non-live local port.')
        if not args.runtime_python.is_absolute() or not args.runtime_python.is_file() or not os.access(args.runtime_python, os.X_OK):
            raise ValueError('Select the existing compatible installed Python runtime.')
        # Reserve one new private receipt before any restoration. Never overwrite it.
        if (not args.receipt.is_absolute() or args.receipt.parent.is_symlink()
                or args.receipt.parent.stat().st_mode & 0o777 != 0o700
                or args.receipt.parent.stat().st_uid != os.getuid()
                or args.receipt.resolve().is_relative_to(ROOT)):
            raise ValueError('Choose a new receipt in an existing owner-private folder outside Git.')
        private_output(args.receipt, b'{"status":"incomplete"}\n')
        for image in (args.journal_image, args.access_image, args.evidence_image):
            private_file(image, 'encrypted recovery image')
        original_hashes = [file_hash(image) for image in (args.journal_image, args.access_image, args.evidence_image)]
        checked = check_release(args.release_dir, manifest_sha256=args.manifest_sha256, source_commit=args.source_commit)
        print('Existing images only. Separate restored copies and test port; the live site/journal/history are untouched.', flush=True)
        print('Enter image passwords only here. No new owner passkey is created: a signed ephemeral test device checks the restored service.', flush=True)
        with ExitStack() as stack:
            password = getpass.getpass('Journal image password (hidden): ')
            journal, manifest, _ = stack.enter_context(journal_copy(args.journal_image, password, ROOT))
            password = getpass.getpass('Access image password (hidden): ')
            setup = stack.enter_context(access_copy(args.access_image, password))
            password = getpass.getpass('Evidence/audit image password (hidden): ')
            _, evidence, _ = stack.enter_context(evidence_copy(args.evidence_image, password))
            password = None
            if source_digests(journal / 'journal.duckdb') != set(evidence['source_fingerprints']):
                raise ValueError('The journal and evidence images do not cover the same accepted lineage.')
            serve_and_probe(args, journal, setup, manifest, checked['index_sha256'])
        if original_hashes != [file_hash(image) for image in (args.journal_image, args.access_image, args.evidence_image)]:
            raise ValueError('An original recovery image changed.')
        receipt = dict(status='passed', checked_at_utc=datetime.now(timezone.utc).isoformat(),
                       source_commit=args.source_commit, elapsed_seconds=round(time.monotonic()-started, 1),
                       scope='disposable_restored_service_signed_synthetic_access',
                       encrypted_images_preserved=True, source_lineage_matched=True,
                       exact_shell=True, trusted_tls=True, current_reports_and_export=True,
                       logout_locked=True, temporary_copies_removed=True,
                       restored_report_read_audits=3, live_write=False, history_activation=False,
                       owner_device_reenrollment=False, hosted_acceptance=False)
        # This file was reserved by this invocation; update only that owned receipt.
        private_file(args.receipt, 'rehearsal receipt', private_parent=True)
        fd = os.open(args.receipt, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, 'w') as output:
            json.dump(receipt, output, indent=2)
        print('Restored protected service passed: trusted HTTPS, fresh synthetic enrollment/login, current reports/CSV and logout lock.', flush=True)
        print('Temporary service/copies removed; original images and live site retained. History remains separate.', flush=True)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('Cancelled; no live restore or restart was performed.', file=sys.stderr)
    except Exception:
        print('Recovery rehearsal incomplete. Check the private image passwords, image compatibility, runtime and free test port. Private values were not logged.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
