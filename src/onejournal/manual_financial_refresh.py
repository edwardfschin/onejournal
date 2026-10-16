"""Mac-only upload -> validated Journal, Portfolio and Reports publication.

The private server setting is the owner's standing conditional publication
instruction, not authority supplied by a broker file. Credentials never enter
this service. Existing adapters and financial contracts remain authoritative.
"""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

import duckdb
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from onejournal.activity_financial_preview import load_activity_financial_preview
from onejournal.activity_publication_preparation import build_report_draft
from onejournal.activity_report_preparation import _json_bytes, _validate_draft
from onejournal.api.broker_current_position_contracts import (
    BrokerCurrentFinancialReleaseAuthorization, build_broker_current_position_valuation_response,
)
from onejournal.brokers.schwab.account_binding import (
    SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA, SchwabAccountPrivateBinding,
)
from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
from onejournal.journal.broker_current_position_valuation_repository import (
    calculate_broker_current_position_result_fingerprint,
    load_broker_current_position_valuation_run, persist_broker_current_position_valuation_run,
)
from onejournal.journal.phase1_reporting_repository import (
    authorize_reporting_release, calculate_report_release_fingerprint, current_breakdowns,
    load_reporting_release, persist_reporting_release, validate_reporting_release,
)
from onejournal.local_web import private_file
from onejournal.mac_journal_backup import copy_private, file_hash
from onejournal.manual_capture_upload import _decode_upload
from onejournal.pnl.broker_current_position_valuation import build_broker_current_position_valuation
from onejournal.provider_connectors.external_acquisition import convert_external_schwab_positions
from onejournal.refresh_activity import confirmed_import
from onejournal.refresh_capture_authorization import (
    ManualRefreshCaptureAuthorization, load_private_capture_authorization, verify_authorized_capture,
)
from onejournal.refresh_intake import read_private

PREFIX = '/api/v1/local-owner/financial-upload'
CONTRACT = 'onejournal.financial-upload.v1'
MAX_BYTES = 29 * 1024 * 1024


def _install_candidate(candidate, db):
    os.replace(candidate, db)
    # This is the commit point. Any later uncertainty must never be reported
    # as a validation rejection with an unchanged journal.
    try:
        descriptor = os.open(db.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise HTTPException(503, 'The update was saved but its durability confirmation failed. Reload saved data to verify it; do not assume the previous release is still active.') from None


class _CandidateDirectory(tempfile.TemporaryDirectory):
    installed = False

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        except OSError:
            if self.installed:
                raise HTTPException(503, 'The update was saved but temporary-file cleanup failed. Reload saved data to verify it.') from None
            raise


def portfolio_authorization(release):
    return BrokerCurrentFinancialReleaseAuthorization(
        owner_acceptance_uid=release.current_owner_acceptance_uid,
        valuation_run_uid=release.current_valuation_run_uid,
        result_fingerprint=release.current_result_fingerprint,
        accepted_at=release.current_owner_accepted_at_utc)


def portfolio_response(db, release):
    run = load_broker_current_position_valuation_run(db, valuation_run_uid=release.current_valuation_run_uid)
    if run is None:
        raise ValueError('Published Portfolio is missing.')
    return build_broker_current_position_valuation_response(run, authorization=portfolio_authorization(release))


class FinancialUploadPublisher:
    def __init__(self, intake, root_authorization):
        self.intake = intake
        self.root = root_authorization
        # Stable server-side scope: another accepted release is not silently
        # opted in. A configuration change explicitly chooses a different root.
        self.policy_uid = 'upload-policy:' + root_authorization.report_release_fingerprint

    def selected_release(self, db):
        with duckdb.connect(str(db), read_only=True) as con:
            root = load_reporting_release(con, report_release_uid=self.root.report_release_uid)
            authorize_reporting_release(root, self.root)
            rows = con.execute('''SELECT report_release_uid FROM phase1_reporting_releases
                WHERE realized_owner_acceptance_uid=? AND release_status='owner_accepted'
                ORDER BY generated_at_utc DESC, report_release_uid DESC LIMIT 1''', [self.policy_uid]).fetchall()
            selected = load_reporting_release(con, report_release_uid=rows[0][0]) if rows else root
        if (selected.accounts != root.accounts or selected.history_revision_uid != root.history_revision_uid
                or selected.coverage_start_date != root.coverage_start_date
                or selected.coverage_end_date < root.coverage_end_date):
            raise ValueError('Saved upload differs from the approved account/history scope.')
        if rows and (not selected.report_release_uid.startswith('manual-upload:')
                     or selected.owner_acceptance_uid != self.policy_uid + ':' + selected.report_release_uid.split(':', 1)[1]):
            raise ValueError('Saved upload publication authority differs.')
        validate_reporting_release(selected)
        return selected

    def _capture(self, files, scope, at):
        # Future packages do not need a chat-created per-package approval. The
        # signed-in owner supplies evidence under the explicit private opt-in;
        # independent private owner/epoch, terms and account pins still apply.
        pins = load_private_capture_authorization(self.intake.authorization_path,
                                                  project_root=self.intake.project_root)
        manifest_bytes = files.get('acquisition-manifest.json', b'')
        document = json.loads(manifest_bytes)
        authority = ManualRefreshCaptureAuthorization(scope, sha256(manifest_bytes).hexdigest(),
            document['acquisition_run_uid'], document['acquisition_approval_id'], pins.owner_uid, pins.owner_epoch_uid)
        acquisition = verify_authorized_capture(files, authorization=authority,
            acknowledgement_bytes=read_private(self.intake.acknowledgement_path, 256 * 1024),
            usage_policy=self.intake.usage_policy, evaluated_at_utc=at)
        return authority, acquisition

    def publish(self, db, positions, activity):
        """Called with the shared database lock; all readers/writers are serialized.

        Validate on one candidate, preserve an exact rollback, then install the
        closed candidate with one atomic rename. The active selection is inside
        that same database, so a crash cannot split data from its authorization.
        No migration, live-row experiment or config-file rewrite is performed.
        """
        db = private_file(Path(db), 'saved journal', private_parent=True)
        if db.stat().st_nlink != 1 or Path(str(db) + '.wal').exists():
            raise ValueError('Journal needs a closed, single-file state before refresh.')
        at = datetime.now(UTC)
        position_authority, acquisition = self._capture(positions, 'current_positions', at)
        activity_authority, activity_acquisition = self._capture(activity, 'activity', at)
        binding = load_schwab_position_private_binding_bytes(read_private(self.intake.account_binding_path, 256 * 1024))
        if any(a.manifest.connection_uid != binding.connection_uid for a in (acquisition, activity_acquisition)):
            raise ValueError('Upload connection differs from the private account.')
        snapshot = convert_external_schwab_positions(acquisition,
            provider_account_hash=binding.provider_account_hash, provider_account_number=binding.provider_account_number,
            source_account_id=binding.source_account_id, mappings=binding.mappings).snapshot
        previous = self.selected_release(db)
        if len(previous.accounts) != 1 or (previous.accounts[0].source_broker, previous.accounts[0].source_account_id) != ('schwab', binding.source_account_id):
            raise ValueError('Upload account differs from the approved report.')
        key = sha256(_json_bytes([self.root.report_release_fingerprint,
            position_authority.manifest_sha256, activity_authority.manifest_sha256])).hexdigest()
        uid = 'manual-upload:' + key
        with duckdb.connect(str(db), read_only=True) as source:
            replay = source.execute('SELECT 1 FROM phase1_reporting_releases WHERE report_release_uid=?', [uid]).fetchone()
            if replay:
                current = load_broker_current_position_valuation_run(db, valuation_run_uid=previous.current_valuation_run_uid)
                return self._receipt(previous, replayed=True, portfolio_asof=current.asof)
            old_run = load_broker_current_position_valuation_run(db, valuation_run_uid=previous.current_valuation_run_uid)
            if old_run is None or (snapshot.connection_uid, snapshot.source_account_id) != (old_run.connection_uid, old_run.source_account_id):
                raise ValueError('Position account differs from the saved Portfolio.')
            if snapshot.retrieved_at <= datetime.fromisoformat(old_run.retrieved_at_utc) or snapshot.asof < old_run.asof:
                raise ValueError('Position evidence must be newer than the saved Portfolio.')
            original = file_hash(db)
            temporary = _CandidateDirectory(prefix='.financial-upload-', dir=db.parent)
            with temporary as directory:
                candidate = Path(directory) / 'journal.duckdb'
                copy_private(db, candidate)
                if file_hash(candidate) != original:
                    raise ValueError('Journal copy differs.')
                # Stage exact immutable bytes. Only the disposable candidate is
                # changed until every financial/read-back check has passed.
                self.intake.stage(positions, publication_authorization=position_authority)
                self.intake.stage(activity, journal_db=candidate, publication_authorization=activity_authority)
                account = SchwabAccountPrivateBinding(SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
                    binding.connection_uid, binding.source_account_id, binding.provider_account_hash, binding.provider_account_number)
                baseline = confirmed_import(candidate, account)
                preview = load_activity_financial_preview(candidate, account,
                    expected_checkpoint_uid=baseline.checkpoint_uid, account_alias=previous.accounts[0].account_alias,
                    current_snapshot=snapshot)
                _validate_draft(preview)
                items = {item.item_uid: item for item in preview.items}
                if any(items.get(item.item_uid) != item for item in previous.items):
                    raise ValueError('A previously published realized result changed or disappeared.')
                if preview.coverage_start_date != previous.coverage_start_date or preview.coverage_end_date < previous.coverage_end_date:
                    raise ValueError('Upload cannot change historical coverage or shorten reports.')
                run = build_broker_current_position_valuation(broker_snapshot=snapshot,
                    evaluated_at=snapshot.retrieved_at, max_snapshot_age_seconds=old_run.max_snapshot_age_seconds,
                    currency_quantum_by_currency=old_run.currency_quantum_by_currency)
                if not (run.complete_portfolio_cost_basis_available and run.complete_portfolio_market_value_available
                        and run.complete_portfolio_unrealized_pnl_available):
                    raise ValueError('Portfolio valuation is incomplete.')
                at = max(at, previous.generated_at_utc + timedelta(microseconds=1))
                draft = build_report_draft(preview, previous, {'revision_uid': baseline.revision_uid},
                    {'acceptance_uid': self.policy_uid}, at)
                release = replace(draft, report_release_uid=uid, current_valuation_run_uid=run.run_uid,
                    current_result_fingerprint=calculate_broker_current_position_result_fingerprint(run),
                    current_owner_acceptance_uid=self.policy_uid + ':' + key, current_owner_accepted_at_utc=at,
                    release_status='owner_accepted', owner_acceptance_uid=self.policy_uid + ':' + key,
                    owner_accepted_at_utc=at, report_release_fingerprint='')
                release = replace(release, report_release_fingerprint=calculate_report_release_fingerprint(release=release))
                validate_reporting_release(release)
                persist_broker_current_position_valuation_run(candidate, run=run, broker_snapshot=snapshot)
                with duckdb.connect(str(candidate)) as con:
                    persist_reporting_release(con, release)
                # Both existing public read-model builders must accept the exact
                # persisted release before any live data is touched.
                portfolio_response(candidate, release)
                current_breakdowns(candidate, release)
                if self.selected_release(candidate) != release:
                    raise ValueError('Candidate active selection differs.')
                if Path(str(candidate) + '.wal').exists() or file_hash(db) != original:
                    raise ValueError('Journal changed while preparing the refresh.')
                # A failed pre-install attempt can leave a verified recovery
                # folder; use a fresh one rather than blocking a safe retry.
                rollback = Path(tempfile.mkdtemp(prefix='rollback-' + key[:16] + '-', dir=self.intake.staging_root))
                copy_private(db, rollback / 'journal.duckdb')
                if file_hash(rollback / 'journal.duckdb') != original:
                    raise ValueError('Rollback copy differs.')
                receipt = {**self._receipt(release, replayed=False, portfolio_asof=snapshot.asof),
                    'state': 'prepared_before_install', 'source_sha256': original,
                    'candidate_sha256': file_hash(candidate), 'policy_uid': self.policy_uid,
                    'position_manifest_sha256': position_authority.manifest_sha256,
                    'activity_manifest_sha256': activity_authority.manifest_sha256}
                path = rollback / 'pre-install.json'
                with path.open('xb') as output:
                    os.chmod(path, 0o600)
                    output.write(_json_bytes(receipt)); output.flush(); os.fsync(output.fileno())
                with candidate.open('rb') as closed:
                    os.fsync(closed.fileno())
                # Same filesystem as target. No connection writes the source;
                # the held DuckDB lock also excludes external process writers.
                _install_candidate(candidate, db)
                temporary.installed = True
        return self._receipt(release, replayed=False, portfolio_asof=snapshot.asof)

    @staticmethod
    def _receipt(release, *, replayed, portfolio_asof):
        return dict(contract_version=CONTRACT, state='published', replayed=replayed,
            report_release_uid=release.report_release_uid,
            portfolio_asof=portfolio_asof.isoformat(),
            coverage_end_date=release.coverage_end_date.isoformat(),
            reportable_count=len(release.items), withheld_count=len(release.omissions))


def register_financial_upload_routes(app, publisher, *, db, db_lock):
    @app.get(PREFIX)
    def status(request: Request):
        return dict(contract_version=CONTRACT, enabled=publisher is not None
                    and getattr(request.app.state, 'passkey_access', None) is not None)

    @app.post(PREFIX, status_code=200)
    async def upload(request: Request):
        if getattr(request.app.state, 'passkey_access', None) is None:
            raise HTTPException(403, 'Protected owner access is required.')
        if publisher is None:
            raise HTTPException(503, 'Financial upload is not enabled.')
        if not request.headers.get('content-type', '').startswith('application/json'):
            raise HTTPException(415, 'JSON is required.')
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BYTES:
                raise HTTPException(413, 'Selected packages are too large. Saved data is unchanged.')
        try:
            document = json.loads(body)
            if not isinstance(document, dict) or set(document) != {'positions', 'activity'}:
                raise ValueError('Both packages are required.')
            positions = _decode_upload(_json_bytes(document['positions']))
            activity = _decode_upload(_json_bytes(document['activity']))
            def save():
                with db_lock:
                    return publisher.publish(db, positions, activity)
            return await run_in_threadpool(save)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, duckdb.Error):
            # Never return adapter errors, file names or financial evidence.
            raise HTTPException(422, 'Upload could not be published. Check that both packages are complete, newer, and for this account. Saved data is unchanged.') from None
