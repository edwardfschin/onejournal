"""Guarded report-only persistence; rehearsal cannot publish or activate runtime.

No migration, broker, credential, history import, config write or service control.
Live persistence requires a separate exact private owner-authority document.
"""
from dataclasses import asdict, fields, replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.activity_live_binding import verify_publication_readiness
from onejournal.activity_report_preparation import _json_bytes, _safe_name
from onejournal.activity_rehearsal import disposable_journal, _proof
from onejournal.journal.phase1_reporting_repository import (
    ReportingRelease, ReportingAccount, RealizedHistoryItem, ReportingOmission,
    ReportingReleaseAuthorization, validate_reporting_release,
    calculate_report_release_fingerprint, load_reporting_release,
    authorize_reporting_release, persist_reporting_release, _utc,
)
from onejournal.journal.phase1_reporting_persistence_operator import (
    REPORTING_TABLES, _latest_migration, _inspect_persistence_target,
    _reporting_counts, _expected_reporting_counts, _existing_reporting_fingerprint,
)
from onejournal.local_web import load_config, private_file
from onejournal.mac_journal_backup import file_hash
from onejournal.refresh_intake import read_private

AUTHORITY='onejournal.activity-publication-authority.v1'
REHEARSAL_PREFIX='offline-rehearsal:'


def load_draft(publication_dir):
    """Decode the already checksummed draft without float conversion or recalculation."""
    document=json.loads(read_private(publication_dir/'prepared-report-draft.json',64*1024*1024))
    if (set(document)!={f.name for f in fields(ReportingRelease)}
            or document['release_status']!='draft' or document['owner_acceptance_uid'] is not None
            or document['owner_accepted_at_utc'] is not None):
        raise ValueError('Expected the exact unpublished report draft.')
    for key in ('current_owner_accepted_at_utc','realized_owner_accepted_at_utc','generated_at_utc'):
        document[key]=_utc(document[key])
    for key in ('coverage_start_date','coverage_end_date'):
        document[key]=date.fromisoformat(document[key])
    document['accounts']=tuple(ReportingAccount(**a) for a in document['accounts'])
    items=[]
    for item in document['items']:
        if not isinstance(item['realized_pnl'],str):
            raise ValueError('Draft money must be exact decimal text.')
        items.append(RealizedHistoryItem(**dict(item,
            realized_pnl=Decimal(item['realized_pnl']),closed_at_utc=_utc(item['closed_at_utc']),
            close_market_date=date.fromisoformat(item['close_market_date']),
            reason_codes=tuple(item['reason_codes']))))
    document['items']=tuple(items)
    document['omissions']=tuple(ReportingOmission(**dict(o,
        close_market_date=date.fromisoformat(o['close_market_date']))) for o in document['omissions'])
    release=ReportingRelease(**document)
    validate_reporting_release(release)
    if _json_bytes(asdict(release))!=read_private(publication_dir/'prepared-report-draft.json',64*1024*1024):
        raise ValueError('Draft typed readback differs.')
    return release


def _promote(draft, *, uid, acceptance_uid, accepted_at):
    release=replace(draft,report_release_uid=uid,release_status='owner_accepted',
        owner_acceptance_uid=acceptance_uid,owner_accepted_at_utc=accepted_at,
        report_release_fingerprint='')
    release=replace(release,report_release_fingerprint=calculate_report_release_fingerprint(release=release))
    validate_reporting_release(release)
    return release


def accepted_release(draft, authority, *, binding_path, publication_dir, backup_receipt_path):
    """Consume future explicit write authority, never financial acceptance alone."""
    required={'contract_version','decision','accepted_scope','approval_source','binding_sha256',
              'publication_plan_sha256','backup_receipt_sha256','owner_acceptance_uid',
              'accepted_at_utc','publication_authorized','runtime_activation_authorized'}
    if (not isinstance(authority,dict) or set(authority)!=required
            or authority['contract_version']!=AUTHORITY or authority['decision']!='accepted'
            or authority['accepted_scope']!='bound_report_only_persistence'
            or authority['approval_source']!='project_owner_explicit_request'
            or authority['publication_authorized'] is not True
            or authority['runtime_activation_authorized'] is not False
            or authority['binding_sha256']!=file_hash(binding_path)
            or authority['publication_plan_sha256']!=file_hash(publication_dir/'publication-plan.json')
            or authority['backup_receipt_sha256']!=file_hash(backup_receipt_path)
            or not isinstance(authority['owner_acceptance_uid'],str)
            or not 1<=len(authority['owner_acceptance_uid'])<=256
            or authority['owner_acceptance_uid'].startswith(REHEARSAL_PREFIX)
            or authority['owner_acceptance_uid'] in (draft.current_owner_acceptance_uid,
                                                    draft.realized_owner_acceptance_uid)):
        raise ValueError('Separate exact live report-persistence authority is required.')
    accepted_at=_utc(authority['accepted_at_utc'])
    if accepted_at<max(draft.generated_at_utc,draft.realized_owner_accepted_at_utc):
        raise ValueError('Publication acceptance must not precede its financial evidence.')
    return _promote(draft,uid='activity-report-release:'+sha256(_json_bytes(authority)).hexdigest(),
                    acceptance_uid=authority['owner_acceptance_uid'],accepted_at=accepted_at)


def _assert_frozen(hashes):
    if any(file_hash(private_file(path,'publication input'))!=digest for path,digest in hashes.items()):
        raise ValueError('Publication input changed; abort without substituting evidence.')


def _inputs(kwargs, authority_path=None):
    """Freeze bytes around the existing readiness proof; no new backup or receipt."""
    config=load_config(kwargs['config_path'],kwargs['project_root'])
    manifest=json.loads(read_private(kwargs['package']/'manifest.json',1024*1024))
    names=list(manifest['sha256'])
    for name in names:
        _safe_name(name)
    paths=[kwargs['binding_path'],kwargs['config_path'],kwargs['backup_receipt_path'],
        kwargs['backup_image'],config.broker_authorization,config.reporting_authorization,
        kwargs['package']/'manifest.json',*(kwargs['package']/n for n in names),
        *(kwargs['publication_dir']/n for n in ('publication-plan.json','acceptance.json',
            'recovery-receipt.json','prepared-report-draft.json'))]
    if authority_path is not None:
        paths.append(authority_path)
    frozen={p:file_hash(private_file(p,'publication input')) for p in paths}
    verify_publication_readiness(**kwargs)
    binding=json.loads(read_private(kwargs['binding_path'],1024*1024))
    plan=json.loads(read_private(kwargs['publication_dir']/'publication-plan.json',1024*1024))
    draft=load_draft(kwargs['publication_dir'])
    if (draft.report_release_uid!=plan['report_release_uid']
            or draft.report_release_fingerprint!=plan['report_release_fingerprint']):
        raise ValueError('Loaded report differs from the prepared plan.')
    predecessor=ReportingReleaseAuthorization(**plan['predecessor'])
    _assert_frozen(frozen)
    return config,binding,draft,predecessor,frozen


def _append_report(target, release, predecessor, *, database_sha256, schema_version, input_guard):
    """One exclusive writer; readback/preservation/input checks precede COMMIT."""
    target=private_file(target,'publication journal',private_parent=True)
    if Path(str(target)+'.wal').exists() or file_hash(target)!=database_sha256:
        raise ValueError('Publication journal changed or has a pending WAL.')
    state,counts,existing_counts,prior=_inspect_persistence_target(target,release,
        predecessor_authorization=predecessor,expected_migration_version=schema_version)
    with duckdb.connect(str(target)) as con:
        if (file_hash(target)!=database_sha256 or Path(str(target)+'.wal').exists()
                or _latest_migration(con)!=schema_version or _reporting_counts(con)!=counts
                or _existing_reporting_fingerprint(con,release.report_release_uid)!=prior):
            raise ValueError('Publication target changed before the exclusive write.')
        names=[r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
            if r[0] not in REPORTING_TABLES]
        preserved=_proof(con,names)
        input_guard()

        def verify_before_commit():
            loaded=load_reporting_release(con,report_release_uid=release.report_release_uid)
            if (loaded!=release
                    or _reporting_counts(con)!=_expected_reporting_counts(existing_counts,release)
                    or _existing_reporting_fingerprint(con,release.report_release_uid)!=prior
                    or _proof(con,names)!=preserved):
                raise ValueError('Report readback or preservation failed; roll back the append.')
            authorize_reporting_release(loaded,ReportingReleaseAuthorization(
                release.report_release_uid,release.report_release_fingerprint,release.owner_acceptance_uid))
            input_guard()

        persist_reporting_release(con,release,before_commit=verify_before_commit)
    return dict(created=state=='would_create',replayed=state=='identical_replay',
                reportable_count=len(release.items),withheld_count=len(release.omissions))


def rehearse_publication(**kwargs):
    config,binding,draft,predecessor,frozen=_inputs(kwargs)
    # Synthetic report authority exists only in memory and this disposable copy.
    # It is not a live authority document and cannot be passed to publish().
    release=_promote(draft,uid=REHEARSAL_PREFIX+draft.report_release_uid,
        acceptance_uid=REHEARSAL_PREFIX+'report-owner',accepted_at=draft.generated_at_utc)
    with disposable_journal(config.journal_db) as target:
        with duckdb.connect(str(target),read_only=True) as con:
            names=[r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
            before=_proof(con,names)
        call=dict(target=target,release=release,predecessor=predecessor,
                  schema_version=binding['live_state']['schema_version'])
        checks=0

        def fail_at_commit():
            nonlocal checks
            checks+=1
            _assert_frozen(frozen)
            if checks==2:
                raise ValueError('offline-injected-before-commit-failure')

        try:
            _append_report(**call,database_sha256=file_hash(target),input_guard=fail_at_commit)
        except ValueError as exc:
            if str(exc)!='offline-injected-before-commit-failure':
                raise
        else:
            raise ValueError('Injected failure did not roll back.')
        with duckdb.connect(str(target),read_only=True) as con:
            if _proof(con,names)!=before:
                raise ValueError('Failed append left partial data on the disposable copy.')
        first=_append_report(**call,database_sha256=file_hash(target),input_guard=lambda:_assert_frozen(frozen))
        replay=_append_report(**call,database_sha256=file_hash(target),input_guard=lambda:_assert_frozen(frozen))
        if not first['created'] or not replay['replayed']:
            raise ValueError('Report append/replay failed on the disposable copy.')
    _assert_frozen(frozen)
    return dict(status='guarded_publication_rehearsed',copy_only=True,
                failure_rollback_verified=True,identical_replay_verified=True,
                exact_readback_verified=True,previous_state_preserved=True,
                reportable_count=len(release.items),withheld_count=len(release.omissions),
                publication_authorized=False,runtime_activation_authorized=False)


def publish(*,authority_path,**kwargs):
    # Refuse missing/preparation-only authority before readiness or any writer.
    authority=json.loads(read_private(authority_path,1024*1024))
    if not isinstance(authority,dict) or authority.get('publication_authorized') is not True:
        raise ValueError('No explicit live publication authority; no writer was opened.')
    config,binding,draft,predecessor,frozen=_inputs(kwargs,authority_path)
    # Use the frozen decision, not an earlier read that may have been revoked
    # or replaced while the readiness proof was running.
    authority=json.loads(read_private(authority_path,1024*1024))
    _assert_frozen(frozen)
    release=accepted_release(draft,authority,binding_path=kwargs['binding_path'],
        publication_dir=kwargs['publication_dir'],backup_receipt_path=kwargs['backup_receipt_path'])
    result=_append_report(config.journal_db,release,predecessor,
        database_sha256=binding['live_state']['sha256']['journal'],
        schema_version=binding['live_state']['schema_version'],input_guard=lambda:_assert_frozen(frozen))
    return dict(result,status='report_persisted_runtime_unchanged',
                report_release_uid=release.report_release_uid,
                report_release_fingerprint=release.report_release_fingerprint,
                runtime_activation_authorized=False)


def main(argv=None):
    import argparse
    import sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('rehearse','publish'))
    for name in ('binding','web-config','package','publication-dir','backup-receipt','backup-image'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--publication-authority',type=Path)
    args=parser.parse_args(argv)
    kwargs=dict(binding_path=args.binding,config_path=args.web_config,
        project_root=Path(__file__).resolve().parents[2],package=args.package,
        publication_dir=args.publication_dir,backup_receipt_path=args.backup_receipt,
        backup_image=args.backup_image)
    try:
        if args.mode=='publish':
            if args.publication_authority is None:
                raise ValueError('A separate explicit publication authority is required.')
            result=publish(authority_path=args.publication_authority,**kwargs)
        else:
            if args.publication_authority is not None:
                raise ValueError('Rehearsal does not consume live publication authority.')
            result=rehearse_publication(**kwargs)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (Exception,KeyboardInterrupt):
        print('Publication command stopped. Check exact authority, unchanged target/input/backup and an available journal lock. A committed report may need read-only confirmation before retry; no automatic rebind, broker request, migration or runtime activation was attempted.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
