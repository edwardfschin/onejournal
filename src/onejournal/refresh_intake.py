"""Offline Schwab refresh handoff/intake; no network or financial database writes.

The credential owner remains external. The only mutable state here is the
explicitly selected private request store. Received evidence stays in its
original private bundle and is revalidated before recording its receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
from onejournal.local_web import private_file
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
    SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    convert_external_schwab_positions,
    load_external_provider_acquisition,
)
from onejournal.provider_connectors.usage_policy import load_provider_usage_policy
from onejournal.refresh_requests import RefreshRequests


def read_private(path: Path, limit: int) -> bytes:
    checked = private_file(path, 'refresh evidence', private_parent=True)
    # Bounded read even if an external process changes the file after stat().
    with checked.open('rb') as stream:
        body = stream.read(limit + 1)
    if not 0 < len(body) <= limit:
        raise ValueError('Refresh evidence size is outside its bound.')
    return body


def position_bundle(root: Path) -> tuple[bytes, dict[str, bytes]]:
    manifest = read_private(root / EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME, 256 * 1024)
    document = json.loads(manifest)
    requests = document.get('requests') if isinstance(document, dict) else None
    if not isinstance(requests, list) or len(requests) != 1 or not isinstance(requests[0], dict):
        raise ValueError('Exactly one position response is required.')
    name = requests[0].get('response_filename')
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
        raise ValueError('Unsafe refresh response name.')
    if {p.name for p in root.iterdir()} != {EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME, name}:
        raise ValueError('Refresh bundle differs from its manifest.')
    return manifest, {name: read_private(root / name, 4 * 1024 * 1024)}


def receive_position_refresh(
    queue: RefreshRequests, *, request_id: str, acquisition_root: Path,
    acknowledgement: Path, position_binding: Path, usage_policy,
    expected_approval_id: str, expected_owner_uid: str,
    expected_owner_epoch_uid: str, evaluated_at: datetime,
) -> bool:
    """Validate in memory, then atomically record a receipt; False is exact replay.

    This does not import positions, calculate P&L, advance transaction coverage,
    publish a report or close review. A malformed/stale/conflicting bundle leaves
    the request untouched so the original evidence can be investigated.
    """
    request = queue.get(request_id)
    if queue.provider != 'schwab' or request['state'] not in ('capturing', 'captured', 'closed'):
        raise ValueError('An explicitly claimed Schwab request is required.')
    manifest, responses = position_bundle(acquisition_root)
    binding = load_schwab_position_private_binding_bytes(read_private(position_binding, 256 * 1024))
    acquisition = load_external_provider_acquisition(
        manifest, response_bytes=responses,
        acknowledgement_bytes=read_private(acknowledgement, 256 * 1024),
        usage_policy=usage_policy, evaluated_at_utc=evaluated_at,
        expected_acquisition_run_uid=request_id,
        expected_acquisition_approval_id=expected_approval_id,
        expected_owner_uid=expected_owner_uid,
        expected_owner_epoch_uid=expected_owner_epoch_uid,
    )
    observed = acquisition.manifest
    if (observed.profile != SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
            or observed.connection_uid != binding.connection_uid
            or observed.controls.oauth_refresh_count != 0):
        raise ValueError('Refresh receipt differs from the supported capture scope.')
    if any(item.requested_at_utc < datetime.fromisoformat(request['requested_at']) for item in observed.requests):
        raise ValueError('Capture predates the website refresh request.')
    converted = convert_external_schwab_positions(
        acquisition, provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id, mappings=binding.mappings,
    )
    if not converted.snapshot.account_complete:
        raise ValueError('A complete current-position snapshot is required.')
    return queue.captured(request_id, acquisition, expected_connection_uid=binding.connection_uid)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-store', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('claim', help='Claim one queued request once; emit credential-free handoff JSON, never execute it.')
    receive = commands.add_parser('receive', help='Validate a transferred position bundle and record its private receipt only.')
    for name in ('acquisition-root', 'acknowledgement', 'position-binding', 'usage-policy'):
        receive.add_argument('--' + name, required=True, type=Path)
    for name in ('request-id', 'expected-approval-id', 'expected-owner-uid', 'expected-owner-epoch-uid'):
        receive.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        queue = RefreshRequests(args.request_store, 'schwab')
        if args.command == 'claim':
            # Durable claim precedes output. A crash cannot automatically
            # reissue work; the owner must reconcile the claimed request first.
            request = queue.claim()
            print(json.dumps({'contract_version': 'onejournal.refresh-handoff.v1',
                              'request': request, 'broker_execution_authorized': False}, sort_keys=True))
        else:
            from datetime import UTC
            changed = receive_position_refresh(
                queue, request_id=args.request_id, acquisition_root=args.acquisition_root,
                acknowledgement=args.acknowledgement, position_binding=args.position_binding,
                usage_policy=load_provider_usage_policy(args.usage_policy),
                expected_approval_id=args.expected_approval_id, expected_owner_uid=args.expected_owner_uid,
                expected_owner_epoch_uid=args.expected_owner_epoch_uid, evaluated_at=datetime.now(UTC),
            )
            print('Refresh evidence validated; review remains pending.' if changed else
                  'Identical refresh receipt already recorded; nothing changed.')
        return 0
    except Exception:
        # Parser/adapter errors may include private symbols, paths or identities.
        # Leave evidence/claim intact; never fall back, retry capture or reset.
        print('Refresh handoff/intake stopped. Check the private store, bundle, account binding and capture authority. No broker call or journal write was made.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
