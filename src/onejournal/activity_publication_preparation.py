"""Owner-accepted activity result to copy-only report publication preparation.

No live target, publication authorization, provider capability or runtime change.
The accepted financial result and a publishable report are separate states.
"""
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.activity_report_preparation import verify_preparation, _json_bytes
from onejournal.activity_financial_preview import load_activity_financial_preview, CURRENT_CALCULATION_REVISION
from onejournal.activity_rehearsal import disposable_journal, _proof
from onejournal.brokers.schwab.account_binding import load_schwab_account_private_binding_bytes
from onejournal.journal.phase1_reporting_repository import (
    ReportingReleaseAuthorization, Phase1ReportingError,
    calculate_report_release_fingerprint, validate_reporting_release,
    load_reporting_release_authorization, load_reporting_release, authorize_reporting_release,
    persist_reporting_release, current_breakdowns, realized_history,
)
from onejournal.journal.phase1_reporting_persistence_operator import (
    REPORTING_TABLES, _existing_reporting_fingerprint, _reporting_counts,
)
from onejournal.mac_access_backup import private_output
from onejournal.mac_evidence_audit_backup import _private_directory
from onejournal.mac_journal_backup import file_hash
from onejournal.refresh_intake import read_private
from onejournal.local_web import private_file

ACCEPTANCE = 'onejournal.activity-result-acceptance.v1'
PLAN = 'onejournal.activity-publication-preparation.v1'


def validate_acceptance(receipt, manifest, preview):
    fields={'contract_version','decision','accepted_scope','approval_source','acceptance_uid',
            'recorded_at_utc','package_fingerprint','result_fingerprint','reportable_count',
            'withheld_count','publication_authorized'}
    if (set(receipt)!=fields or receipt['contract_version']!=ACCEPTANCE
            or receipt['decision']!='accepted' or receipt['accepted_scope']!='bounded_realized_activity_draft'
            or receipt['approval_source']!='project_owner_explicit_request'
            or receipt['publication_authorized'] is not False
            or not isinstance(receipt['acceptance_uid'],str) or not 1<=len(receipt['acceptance_uid'])<=256
            or receipt['package_fingerprint']!=manifest['package_fingerprint']
            or receipt['result_fingerprint']!=preview.result_fingerprint
            or type(receipt['reportable_count']) is not int or receipt['reportable_count']!=len(preview.items)
            or type(receipt['withheld_count']) is not int or receipt['withheld_count']!=len(preview.omissions)
            or not preview.calculation_version.endswith('+'+CURRENT_CALCULATION_REVISION)):
        raise ValueError('Owner acceptance differs from the exact corrected financial draft.')
    at=datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z','+00:00'))
    if at.tzinfo is None or at.utcoffset()!=UTC.utcoffset(at) or at<preview.checkpoint_utc:
        raise ValueError('Acceptance recording time must be UTC and not precede its evidence.')
    return at


def build_report_draft(preview, predecessor, provenance, acceptance, recorded_at):
    if set(preview.accounts)!=set(predecessor.accounts):
        raise ValueError('Prepared report account scope differs from its predecessor.')
    # Reuse already accepted current valuation exactly, without claiming a new
    # portfolio refresh. Only the realized branch has this new owner acceptance.
    release=replace(predecessor,
        report_release_uid='activity-report-draft:'+sha256(_json_bytes(acceptance)).hexdigest(),
        realized_calculation_run_id='activity-financial-result:'+preview.result_fingerprint,
        realized_result_fingerprint=preview.result_fingerprint,
        realized_owner_acceptance_uid=acceptance['acceptance_uid'],
        realized_owner_accepted_at_utc=recorded_at,history_revision_uid=provenance['revision_uid'],
        coverage_start_date=preview.coverage_start_date,coverage_end_date=preview.coverage_end_date,
        calculation_version=preview.calculation_version,generated_at_utc=recorded_at,
        release_status='draft',owner_acceptance_uid=None,owner_accepted_at_utc=None,
        accounts=tuple(sorted(preview.accounts,key=lambda a:(a.source_broker,a.source_account_id))),
        items=tuple(sorted(preview.items,key=lambda i:i.item_uid)),
        omissions=tuple(sorted(preview.omissions,key=lambda o:o.omission_uid)),
        report_release_fingerprint='')
    release=replace(release,report_release_fingerprint=calculate_report_release_fingerprint(release=release))
    validate_reporting_release(release)
    return release


def rehearse_report_draft(source, release):
    if release.release_status!='draft' or release.owner_acceptance_uid is not None:
        raise ValueError('Preparation rehearses only an unpublished report draft.')
    validate_reporting_release(release)
    with disposable_journal(source) as target:
        with duckdb.connect(str(target)) as con:
            names=[r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
                   if r[0] not in REPORTING_TABLES]
            before=_proof(con,names)
            prior=_existing_reporting_fingerprint(con,release.report_release_uid)
            counts=_reporting_counts(con)
            persist_reporting_release(con,release)
            first=_reporting_counts(con)
            persist_reporting_release(con,release)
            loaded=load_reporting_release(con,report_release_uid=release.report_release_uid)
            if (loaded!=release or _reporting_counts(con)!=first
                    or first!=tuple(a+b for a,b in zip(counts,(1,len(release.accounts),len(release.items),len(release.omissions),0)))
                    or _existing_reporting_fingerprint(con,release.report_release_uid)!=prior
                    or _proof(con,names)!=before):
                raise ValueError('Disposable report persistence/readback or preservation differs.')
            try:
                authorize_reporting_release(loaded,ReportingReleaseAuthorization(
                    loaded.report_release_uid,loaded.report_release_fingerprint,'not-publication-authority'))
            except Phase1ReportingError:
                pass
            else:
                raise ValueError('An unpublished draft unexpectedly passed runtime authorization.')
            quality,items,reasons=realized_history(loaded,from_date=loaded.coverage_start_date,to_date=loaded.coverage_end_date)
            if items!=loaded.items or sum(reasons.values())!=len(loaded.omissions):
                raise ValueError('Prepared reporting read model differs.')
    return dict(copy_only=True,identical_replay_verified=True,exact_readback_verified=True,
                previous_state_preserved=True,runtime_authorization_refused=True,quality=quality)


def selected_predecessor(db, source_authorization, selected_authorization=None):
    """Keep the immutable source package, but explicitly select accepted current authority.

    No latest-release lookup or inference. The selected release must already be
    present and owner-accepted in the backed-up snapshot.
    """
    path=private_file(selected_authorization or source_authorization,
                      'selected predecessor authorization',private_parent=True)
    authority=load_reporting_release_authorization(path)
    with duckdb.connect(str(db),read_only=True) as con:
        predecessor=load_reporting_release(con,report_release_uid=authority.report_release_uid)
        authorize_reporting_release(predecessor,authority)
    return authority,predecessor


def prepare_publication(*, package, acceptance_path, recovery_receipt_path, output_dir,
                        predecessor_authorization=None):
    output=Path(output_dir)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError('Choose a new absolute private publication-preparation directory.')
    parent=_private_directory(output.parent,'publication-preparation parent')
    if (output.resolve().is_relative_to(Path(package).resolve())
            or any((p/'.git').exists() for p in (parent,*parent.parents))):
        raise ValueError('Keep publication preparation outside the immutable draft and Git.')
    manifest=verify_preparation(package)
    acceptance_bytes=read_private(acceptance_path,1024*1024)
    acceptance=json.loads(acceptance_bytes)
    recovery_bytes=read_private(recovery_receipt_path,1024*1024)
    recovery=json.loads(recovery_bytes)
    if (recovery.get('status')!='encrypted_draft_recovery_verified'
            or recovery.get('package_fingerprint')!=manifest['package_fingerprint']
            or recovery.get('file_count')!=len(manifest['sha256'])
            or recovery.get('publication_authorized') is not False):
        raise ValueError('Encrypted recovery receipt differs from the selected draft.')
    binding=load_schwab_account_private_binding_bytes(read_private(package/'account-binding.json',256*1024))
    preview=load_activity_financial_preview(package/'journal.duckdb',binding,
        expected_checkpoint_uid=manifest['checkpoint_uid'],account_alias=manifest['account_alias'])
    recorded_at=validate_acceptance(acceptance,manifest,preview)
    authority,predecessor=selected_predecessor(package/'journal.duckdb',
        package/'predecessor-authorization.json',predecessor_authorization)
    current_breakdowns(package/'journal.duckdb',predecessor)  # Exact retained current-valuation fingerprint.
    provenance=json.loads(read_private(package/'provenance.json',1024*1024))
    release=build_report_draft(preview,predecessor,provenance,acceptance,recorded_at)
    rehearsal=rehearse_report_draft(package/'journal.duckdb',release)
    verify_preparation(package)  # Original backed-up bytes remain unchanged.
    output.mkdir(mode=0o700)
    private_output(output/'acceptance.json',acceptance_bytes)
    private_output(output/'recovery-receipt.json',recovery_bytes)
    private_output(output/'prepared-report-draft.json',_json_bytes(asdict(release)))
    plan=dict(contract_version=PLAN,financial_result_owner_accepted=True,publication_authorized=False,
        runtime_activation_authorized=False,live_target_bound=False,
        package_fingerprint=manifest['package_fingerprint'],result_fingerprint=preview.result_fingerprint,
        checkpoint_uid=manifest['checkpoint_uid'],snapshot_sha256=manifest['sha256']['journal.duckdb'],
        predecessor=asdict(authority),report_release_uid=release.report_release_uid,
        predecessor_selection=('explicit_owner_selected_current' if predecessor_authorization is not None
                               else 'backed_up_source_predecessor'),
        report_release_fingerprint=release.report_release_fingerprint,
        current_valuation_mode='retain_exact_predecessor_no_refresh',
        current_result_fingerprint=release.current_result_fingerprint,
        reportable_count=len(release.items),withheld_count=len(release.omissions),rehearsal=rehearsal,
        remaining_live_preconditions=['exact_live_target_and_schema_binding','fresh_verified_live_backup',
                                     'explicit_live_publication_authority','separate_runtime_activation_scope'],
        sha256={p.name:file_hash(p) for p in output.iterdir()})
    private_output(output/'publication-plan.json',_json_bytes(plan))  # Completion marker last.
    return dict(status='guarded_publication_preparation_rehearsed',publication_authorized=False,
                financial_result_owner_accepted=True,copy_only=True,
                reportable_count=len(release.items),withheld_count=len(release.omissions))


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','acceptance','recovery-receipt','output-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--predecessor-authorization',type=Path,
        help='Explicit already accepted active report authority; never select latest or change the source package.')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(prepare_publication(package=args.package,acceptance_path=args.acceptance,
            recovery_receipt_path=args.recovery_receipt,output_dir=args.output_dir,
            predecessor_authorization=args.predecessor_authorization),sort_keys=True))
        return 0
    except Exception:
        print('Publication preparation stopped. Check exact owner acceptance, verified draft/recovery and new private output. No live write, publication, broker call or runtime change occurred.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
