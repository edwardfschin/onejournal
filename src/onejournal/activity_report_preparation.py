"""Guarded activity report draft and disposable recovery rehearsal.

Copies only selected private evidence. Creates no accepted authorization, live
database write, service, encrypted/off-device backup, or broker capability.
"""
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import duckdb

from onejournal.activity_financial_preview import (
    load_activity_financial_preview, report_preview, report_preview_csv, trade_preview,
)
from onejournal.activity_rehearsal import disposable_journal, prepare_copy, _proof
from onejournal.brokers.schwab.account_binding import load_schwab_account_private_binding_bytes
from onejournal.journal.phase1_reporting_repository import (
    load_reporting_release_authorization, load_reporting_release, authorize_reporting_release,
    _decimal_text,
)
from onejournal.journal.schwab_evidence_assembly import canonical_schwab_evidence_json
from onejournal.local_web import private_file
from onejournal.mac_access_backup import private_output
from onejournal.mac_evidence_audit_backup import source_digests, exact_evidence, _private_directory, _relative_name
from onejournal.mac_journal_backup import copy_private, file_hash
from onejournal.refresh_activity import _confirmed_import
from onejournal.refresh_intake import read_private

CONTRACT = 'onejournal.activity-report-preparation.v1'
FIXED = {'journal.duckdb','account-binding.json','report.json','realized-history.csv',
         'trades.json','omissions.json','provenance.json'}


def _json_bytes(value):
    return (canonical_schwab_evidence_json(value)+'\n').encode()


def _documents(preview):
    _validate_draft(preview)
    filters = dict(from_date=preview.coverage_start_date,to_date=preview.coverage_end_date)
    return {'report.json':_json_bytes(report_preview(preview,**filters)),
            'realized-history.csv':report_preview_csv(preview,**filters).encode(),
            'trades.json':_json_bytes(dict(contract_version=CONTRACT,owner_accepted=False,
                trades=[trade_preview(preview,t['episode_uid']).model_dump(mode='json') for t in preview.trades])),
            'omissions.json':_json_bytes(dict(contract_version=CONTRACT,owner_accepted=False,
                items=[asdict(o) for o in preview.omissions]))}


def _validate_draft(preview):
    """Check release storage/identity limits without fabricating acceptance."""
    if (len({i.item_uid for i in preview.items})!=len(preview.items)
            or len({o.omission_uid for o in preview.omissions})!=len(preview.omissions)):
        raise ValueError('Draft financial identities are duplicated.')
    for item in preview.items:
        integer,_,fraction = _decimal_text(item.realized_pnl).lstrip('-').partition('.')
        if len(integer.lstrip('0'))>11 or len(fraction)>27:
            raise ValueError('Draft result exceeds existing release decimal precision.')
    if any(not preview.coverage_start_date<=row.close_market_date<=preview.coverage_end_date
           for row in (*preview.items,*preview.omissions)):
        raise ValueError('Draft result is outside report coverage.')


def _predecessor(con, authorization_path):
    count = con.execute("SELECT COUNT(*) FROM phase1_reporting_releases WHERE release_status='owner_accepted'").fetchone()[0]
    if authorization_path is None:
        if count:
            raise ValueError('Select the exact predecessor report authorization.')
        return None
    path = private_file(authorization_path,'predecessor authorization',private_parent=True)
    authority = load_reporting_release_authorization(path)
    release = load_reporting_release(con,report_release_uid=authority.report_release_uid)
    authorize_reporting_release(release,authority)
    return asdict(authority)


def _snapshot_guard(db,binding,expected_checkpoint_uid,account_alias,predecessor_path):
    with duckdb.connect(str(db),read_only=True) as con:
        con.execute('BEGIN TRANSACTION')
        baseline = _confirmed_import(con,binding)
        if (baseline.checkpoint_uid or baseline.assembly.result_fingerprint)!=expected_checkpoint_uid:
            raise ValueError('Preparation checkpoint differs.')
        predecessor = _predecessor(con,predecessor_path)
        if predecessor:
            prior = load_reporting_release(con,report_release_uid=predecessor['report_release_uid'])
            if {(a.source_broker,a.source_account_id,a.account_alias) for a in prior.accounts}!={('schwab',binding.source_account_id,account_alias)}:
                raise ValueError('Predecessor account scope differs.')
        return dict(activation_uid=baseline.activation_uid,revision_uid=baseline.revision_uid,
            assembly_fingerprint=baseline.assembly.result_fingerprint,checkpoint_uid=expected_checkpoint_uid,
            predecessor=predecessor)


def _safe_name(name):
    if name in FIXED or name=='predecessor-authorization.json':
        return
    if isinstance(name,str) and name.startswith('evidence/'):
        _relative_name(name.removeprefix('evidence/'))
        return
    raise ValueError('Unexpected preparation file.')


def verify_preparation(root):
    """Hash every file and regenerate the draft from the recovered snapshot."""
    root = _private_directory(root,'report preparation')
    document = json.loads(read_private(root/'manifest.json',1024*1024))
    expected_fields = {'contract_version','release_status','owner_acceptance','publication_authorized',
        'created_at_utc','checkpoint_uid','result_fingerprint','position_snapshot_utc','account_alias',
        'source_database_sha256','source_fingerprints','sha256','package_fingerprint'}
    if (set(document)!=expected_fields or document['contract_version']!=CONTRACT
            or document['release_status']!='prepared_pending_owner_acceptance'
            or document['owner_acceptance'] is not None or document['publication_authorized'] is not False):
        raise ValueError('Preparation is not an unaccepted draft.')
    unsigned = {k:v for k,v in document.items() if k!='package_fingerprint'}
    if sha256(_json_bytes(unsigned)).hexdigest()!=document['package_fingerprint']:
        raise ValueError('Preparation manifest fingerprint differs.')
    hashes = document['sha256']
    if not isinstance(hashes,dict) or not FIXED.issubset(hashes):
        raise ValueError('Preparation recovery files are incomplete.')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(hashes)|{'manifest.json'}:
        raise ValueError('Preparation has unexpected or missing files.')
    for name,digest in hashes.items():
        _safe_name(name)
        path = private_file(root/name,'preparation file',private_parent=True)
        if file_hash(path)!=digest:
            raise ValueError('Preparation file checksum differs.')
    binding = load_schwab_account_private_binding_bytes(read_private(root/'account-binding.json',256*1024))
    db = root/'journal.duckdb'
    before = file_hash(db)
    predecessor_path = root/'predecessor-authorization.json' if 'predecessor-authorization.json' in hashes else None
    guard = _snapshot_guard(db,binding,document['checkpoint_uid'],document['account_alias'],predecessor_path)
    if _json_bytes(guard)!=read_private(root/'provenance.json',1024*1024):
        raise ValueError('Preparation source lineage differs.')
    preview = load_activity_financial_preview(db,binding,
        expected_checkpoint_uid=document['checkpoint_uid'],account_alias=document['account_alias'])
    if preview.result_fingerprint!=document['result_fingerprint'] or preview.position_snapshot_utc.isoformat()!=document['position_snapshot_utc']:
        raise ValueError('Recovered financial result differs.')
    for name,expected in _documents(preview).items():
        if (root/name).read_bytes()!=expected:
            raise ValueError('Recovered report or Trades payload differs.')
    required = source_digests(db)
    if sorted(required)!=document['source_fingerprints']:
        raise ValueError('Recovered source allowlist differs.')
    selected = exact_evidence(root/'evidence',required)
    if {'evidence/'+n for n in selected} != {n for n in hashes if n.startswith('evidence/')}:
        raise ValueError('Recovered evidence selection differs.')
    if file_hash(db)!=before:
        raise ValueError('Preparation verification wrote journal state.')
    return document


def _copy_files(source,target,names):
    for name in sorted(names):
        _safe_name(name) if name!='manifest.json' else None
        destination = target/name
        _private_parents(destination.parent,target)
        copy_private(source/name,destination)


def _private_parents(path,root):
    """Create every intermediate directory as 0700, not mkdir's 0755 default."""
    current = root
    for part in path.relative_to(root).parts:
        current = current/part
        current.mkdir(mode=0o700,exist_ok=True)
        _private_directory(current,'preparation subdirectory')


def rehearse_recovery(package):
    """Restore only into a new owner-private directory and reproduce the result."""
    manifest = verify_preparation(package)
    with tempfile.TemporaryDirectory(prefix='onejournal-report-restore-',dir='/private/tmp') as directory:
        restored = Path(directory)
        _copy_files(package,restored,set(manifest['sha256'])|{'manifest.json'})
        if verify_preparation(restored)!=manifest:
            raise ValueError('Recovered preparation differs.')
    return True


def prepare_activity_release(*, source_db, account_binding, raw_root, expected_checkpoint_uid,
                            account_alias, output_dir, predecessor_authorization=None):
    """Reproduce and verify privately; publish a new draft folder, never authority."""
    output = Path(output_dir)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError('Use a new absolute preparation directory.')
    parent = _private_directory(output.parent,'preparation parent')
    evidence_root = _private_directory(raw_root,'source evidence root')
    if output.resolve().is_relative_to(evidence_root):
        raise ValueError('Keep preparation outside the source-evidence tree.')
    if any((p/'.git').exists() for p in (parent,*parent.parents)):
        raise ValueError('Private preparation must stay outside Git.')
    binding_bytes = read_private(account_binding,256*1024)
    binding = load_schwab_account_private_binding_bytes(binding_bytes)
    original = file_hash(private_file(source_db,'source journal',private_parent=True))
    with disposable_journal(source_db) as copy:
        state = prepare_copy(copy)
        names = [r[1] for r in state['relations']]
        with duckdb.connect(str(copy),read_only=True) as con:
            before = _proof(con,names)
        guard = _snapshot_guard(copy,binding,expected_checkpoint_uid,account_alias,predecessor_authorization)
        preview = load_activity_financial_preview(copy,binding,
            expected_checkpoint_uid=expected_checkpoint_uid,account_alias=account_alias)
        required = source_digests(copy)
        matched = exact_evidence(evidence_root,required)
        with tempfile.TemporaryDirectory(prefix='onejournal-report-stage-',dir='/private/tmp') as directory:
            stage = Path(directory)
            copy_private(copy,stage/'journal.duckdb')
            private_output(stage/'account-binding.json',binding_bytes)
            if predecessor_authorization is not None:
                private_output(stage/'predecessor-authorization.json',read_private(predecessor_authorization,256*1024))
            for name,body in _documents(preview).items():
                private_output(stage/name,body)
            private_output(stage/'provenance.json',_json_bytes(guard))
            (stage/'evidence').mkdir(mode=0o700)
            for name,(path,digest) in matched.items():
                target = stage/'evidence'/name
                _private_parents(target.parent,stage)
                copy_private(path,target)
                if file_hash(path)!=digest or file_hash(target)!=digest:
                    raise ValueError('Source evidence changed during preparation.')
            hashes = {p.relative_to(stage).as_posix():file_hash(p) for p in stage.rglob('*') if p.is_file()}
            manifest = dict(contract_version=CONTRACT,release_status='prepared_pending_owner_acceptance',
                owner_acceptance=None,publication_authorized=False,created_at_utc=datetime.now(UTC).isoformat(),
                checkpoint_uid=expected_checkpoint_uid,result_fingerprint=preview.result_fingerprint,
                position_snapshot_utc=preview.position_snapshot_utc.isoformat(),account_alias=account_alias,
                source_database_sha256=original,source_fingerprints=sorted(required),sha256=hashes)
            manifest['package_fingerprint'] = sha256(_json_bytes(manifest)).hexdigest()
            private_output(stage/'manifest.json',_json_bytes(manifest))
            rehearse_recovery(stage)
            with duckdb.connect(str(copy),read_only=True) as con:
                if _proof(con,names)!=before:
                    raise ValueError('Preparation changed original copied relations.')
            if file_hash(source_db)!=original:
                raise ValueError('Source journal changed during preparation.')
            # Reserve the destination exclusively. The completion manifest is
            # copied last; failures cannot overwrite any prior package.
            output.mkdir(mode=0o700)
            _copy_files(stage,output,set(hashes))
            copy_private(stage/'manifest.json',output/'manifest.json')
            verify_preparation(output)
    return dict(status='prepared_and_recovery_rehearsed',release_status='prepared_pending_owner_acceptance',
                original_unchanged=True,publication_authorized=False,encrypted_backup_created=False)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('db','account-binding','raw-root','output-dir','predecessor-authorization'):
        parser.add_argument('--'+name,type=Path,required=name!='predecessor-authorization')
    parser.add_argument('--expected-checkpoint-uid',required=True)
    parser.add_argument('--account-alias',required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_activity_release(source_db=args.db,account_binding=args.account_binding,
            raw_root=args.raw_root,output_dir=args.output_dir,predecessor_authorization=args.predecessor_authorization,
            expected_checkpoint_uid=args.expected_checkpoint_uid,account_alias=args.account_alias)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        print('Release preparation stopped. Check the pinned checkpoint, predecessor authority, private evidence and new output folder. No live write or broker call occurred; any incomplete output must not be used.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
