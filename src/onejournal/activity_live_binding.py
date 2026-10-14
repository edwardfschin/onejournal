"""Read-only live report-target binding and existing encrypted backup integration.

No migration, publication, broker access or service control capability.
"""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.activity_report_preparation import verify_preparation, _json_bytes
from onejournal.activity_publication_preparation import PLAN, validate_acceptance, build_report_draft
from onejournal.activity_financial_preview import load_activity_financial_preview
from onejournal.brokers.schwab.account_binding import load_schwab_account_private_binding_bytes
from onejournal.local_web import load_config, configured_app
from onejournal.mac_access_backup import private_output
from onejournal.mac_evidence_audit_backup import _private_directory
from onejournal.mac_journal_backup import file_hash, inventory, create_backup
from onejournal.journal.phase1_reporting_repository import (
    load_reporting_release_authorization, load_reporting_release, authorize_reporting_release,
)
from onejournal.refresh_intake import read_private
from onejournal.journal.phase1_reporting_persistence_operator import REPORTING_TABLES

CONTRACT='onejournal.activity-live-target-binding.v1'


def compatible_report_columns(live_inventory,snapshot_inventory):
    live={tuple(c) for c in live_inventory['columns'] if c[1] in REPORTING_TABLES}
    expected={tuple(c) for c in snapshot_inventory['columns'] if c[1] in REPORTING_TABLES}
    if not expected or live!=expected:
        raise ValueError('Live reporting columns/decimal precision differ from the rehearsed snapshot.')


def new_private_output(path):
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError('Choose a new absolute private output.')
    parent=_private_directory(path.parent,'output parent')
    if any((p/'.git').exists() for p in (parent,*parent.parents)):
        raise ValueError('Keep private bindings and receipts outside Git.')


def target_state(config_path, project_root):
    config=load_config(config_path,project_root)
    paths={'journal':config.journal_db,'config':config_path,'broker_authorization':config.broker_authorization,
           'report_authorization':config.reporting_authorization}
    if any(p is None for p in paths.values()) or Path(str(config.journal_db)+'.wal').exists():
        raise ValueError('A clean live journal and exact release configuration are required.')
    before={k:file_hash(p) for k,p in paths.items()}
    with duckdb.connect(str(config.journal_db),read_only=True) as con:
        ledger=con.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall()
        version=con.execute("SELECT version FROM schema_migrations WHERE status='applied' ORDER BY CAST(version AS INTEGER) DESC LIMIT 1").fetchone()[0]
        schema=inventory(con)
    if before!={k:file_hash(p) for k,p in paths.items()} or Path(str(config.journal_db)+'.wal').exists():
        raise ValueError('Live target changed during read-only binding.')
    return dict(paths={k:str(p) for k,p in paths.items()},sha256=before,schema_version=version,
                # Hash native storage timestamps as strings, without inventing
                # a timezone for the ledger's TIMESTAMP (not TIMESTAMPTZ) column.
                migration_ledger_sha256=sha256(json.dumps(ledger,default=str,separators=(',',':')).encode()).hexdigest(),
                schema_inventory_sha256=sha256(_json_bytes(schema)).hexdigest(),relation_count=len(schema['relations']))


def bind_live_target(*,config_path,project_root,package,publication_dir,output,expected_schema_version):
    new_private_output(output)
    manifest=verify_preparation(package)
    plan=json.loads(read_private(publication_dir/'publication-plan.json',1024*1024))
    if (plan.get('contract_version')!=PLAN or plan.get('financial_result_owner_accepted') is not True
            or plan.get('publication_authorized') is not False or plan.get('runtime_activation_authorized') is not False
            or plan.get('package_fingerprint')!=manifest['package_fingerprint']
            or set(plan.get('sha256',{}))!={'acceptance.json','recovery-receipt.json','prepared-report-draft.json'}):
        raise ValueError('Publication preparation is not the exact accepted unpublished draft.')
    for name,digest in plan['sha256'].items():
        if sha256(read_private(publication_dir/name,64*1024*1024)).hexdigest()!=digest:
            raise ValueError('Prepared publication inputs changed.')
    before=target_state(config_path,project_root)
    if before['schema_version']!=expected_schema_version:
        raise ValueError('Live schema differs from the explicitly pinned version.')
    config=load_config(config_path,project_root)
    configured_app(config)  # Read-only existing release/schema checks; no request/audit/server.
    with duckdb.connect(str(config.journal_db),read_only=True) as live, \
         duckdb.connect(str(package/'journal.duckdb'),read_only=True) as snapshot:
        compatible_report_columns(inventory(live),inventory(snapshot))
    binding=load_schwab_account_private_binding_bytes(read_private(package/'account-binding.json',256*1024))
    preview=load_activity_financial_preview(config.journal_db,binding,
        expected_checkpoint_uid=plan['checkpoint_uid'],account_alias=manifest['account_alias'])
    if preview.result_fingerprint!=manifest['result_fingerprint'] or preview.result_fingerprint!=plan['result_fingerprint']:
        raise ValueError('Live accepted financial result differs.')
    acceptance=json.loads(read_private(publication_dir/'acceptance.json',1024*1024))
    recorded_at=validate_acceptance(acceptance,manifest,preview)
    authority=load_reporting_release_authorization(config.reporting_authorization)
    if asdict(authority)!=plan['predecessor']:
        raise ValueError('Live report predecessor differs from publication preparation.')
    with duckdb.connect(str(config.journal_db),read_only=True) as con:
        predecessor=load_reporting_release(con,report_release_uid=authority.report_release_uid)
        authorize_reporting_release(predecessor,authority)
    provenance=json.loads(read_private(package/'provenance.json',1024*1024))
    release=build_report_draft(preview,predecessor,provenance,acceptance,recorded_at)
    if (release.report_release_fingerprint!=plan['report_release_fingerprint']
            or _json_bytes(asdict(release))!=read_private(publication_dir/'prepared-report-draft.json',64*1024*1024)
            or target_state(config_path,project_root)!=before):
        raise ValueError('Bound report or live target differs.')
    receipt=dict(contract_version=CONTRACT,live_target_bound=True,live_state=before,
        publication_plan_sha256=file_hash(publication_dir/'publication-plan.json'),
        package_fingerprint=manifest['package_fingerprint'],result_fingerprint=preview.result_fingerprint,
        report_release_fingerprint=release.report_release_fingerprint,
        reportable_count=len(release.items),withheld_count=len(release.omissions),
        migration_performed=False,report_only_schema_compatible=True,
        publication_authorized=False,runtime_activation_authorized=False)
    private_output(output,_json_bytes(receipt))
    return receipt


def verify_bound_target(binding_path,config_path,project_root):
    receipt=json.loads(read_private(binding_path,1024*1024))
    if (receipt.get('contract_version')!=CONTRACT or receipt.get('live_target_bound') is not True
            or receipt.get('publication_authorized') is not False
            or receipt.get('runtime_activation_authorized') is not False
            or receipt.get('live_state')!=target_state(config_path,project_root)):
        raise ValueError('Live target binding is stale or invalid; rebind before backup/publication.')
    return receipt


def backup_bound_target(*,binding_path,config_path,project_root,destination,password,receipt_path):
    new_private_output(receipt_path)
    binding=verify_bound_target(binding_path,config_path,project_root)
    count=create_backup(config_path,destination,password,project_root)  # Existing AES-256 USB restoration proof.
    verify_bound_target(binding_path,config_path,project_root)
    if count!=binding['live_state']['relation_count']:
        raise ValueError('Verified image relation count differs from its target binding.')
    result=dict(status='bound_live_journal_backup_verified',binding_sha256=file_hash(binding_path),
        live_journal_sha256=binding['live_state']['sha256']['journal'],image_sha256=file_hash(destination),
        relation_count=count,publication_authorized=False,runtime_activation_authorized=False)
    private_output(receipt_path,_json_bytes(result))
    return result
