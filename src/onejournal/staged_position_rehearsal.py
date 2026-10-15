"""Rehearse a verified manual current-position capture on a disposable journal.

The accepted Mac position release supplies the existing age and currency
precision policy. This module cannot authorize or publish a replacement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from onejournal.activity_rehearsal import disposable_journal, prepare_copy
from onejournal.api.broker_current_position_contracts import (
    BrokerCurrentFinancialReleaseAuthorization,
    build_broker_current_position_valuation_response,
)
from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
from onejournal.journal.broker_current_position_valuation_repository import (
    calculate_broker_current_position_result_fingerprint,
    load_broker_current_position_valuation_run,
    persist_broker_current_position_valuation_run,
)
from onejournal.local_web import private_directory
from onejournal.manual_capture_upload import ManualCaptureIntake
from onejournal.pnl.broker_current_position_valuation import build_broker_current_position_valuation
from onejournal.provider_connectors.external_acquisition import convert_external_schwab_positions
from onejournal.refresh_capture_authorization import (
    load_private_capture_authorization, verify_authorized_capture,
)
from onejournal.refresh_intake import position_bundle, read_private


CONTRACT = "onejournal.staged-position-rehearsal.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def rehearse_staged_position(
    *, intake: ManualCaptureIntake, manifest_sha256: str, source_db: Path,
    current_authorization: BrokerCurrentFinancialReleaseAuthorization,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Append one position observation and valuation to a copy, never the source."""
    if not isinstance(manifest_sha256, str) or not _DIGEST.fullmatch(manifest_sha256):
        raise ValueError("A pinned staged manifest digest is required.")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
        raise ValueError("Evaluation time must be a UTC instant.")
    root = private_directory(intake.staging_root / manifest_sha256, "staged position capture")
    manifest, responses = position_bundle(root)
    files = {"acquisition-manifest.json": manifest, **responses}
    receipt = intake.stage(files)
    if (not receipt["replayed"] or receipt["scope"] != "current_positions"
            or receipt["manifest_sha256"] != manifest_sha256):
        raise ValueError("The staged position package or private approval changed.")
    authority = load_private_capture_authorization(
        intake.authorization_path, project_root=intake.project_root
    )
    acquisition = verify_authorized_capture(
        files, authorization=authority,
        acknowledgement_bytes=read_private(intake.acknowledgement_path, 256 * 1024),
        usage_policy=intake.usage_policy, evaluated_at_utc=evaluated_at,
    )
    binding = load_schwab_position_private_binding_bytes(
        read_private(intake.account_binding_path, 256 * 1024)
    )
    converted = convert_external_schwab_positions(
        acquisition, provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id, mappings=binding.mappings,
    )
    snapshot = converted.snapshot
    if not snapshot.account_complete:
        raise ValueError("Only a complete current-position observation can be rehearsed.")
    with disposable_journal(source_db) as copy:
        prepare_copy(copy)
        previous = load_broker_current_position_valuation_run(
            copy, valuation_run_uid=current_authorization.valuation_run_uid
        )
        if previous is None:
            raise ValueError("The selected prior position release is missing.")
        build_broker_current_position_valuation_response(
            previous, authorization=current_authorization
        )
        if (previous.source_broker != "schwab"
                or (previous.connection_uid, previous.source_account_id)
                != (binding.connection_uid, binding.source_account_id)):
            raise ValueError("The position capture differs from the released account.")
        previous_retrieved = datetime.fromisoformat(previous.retrieved_at_utc)
        if (snapshot.asof < previous.asof
                or snapshot.retrieved_at < previous_retrieved
                or (snapshot.retrieved_at == previous_retrieved
                    and snapshot.snapshot_uid != previous.snapshot_uid)):
            raise ValueError("The position observation would regress the accepted snapshot.")
        run = build_broker_current_position_valuation(
            broker_snapshot=snapshot, evaluated_at=evaluated_at,
            max_snapshot_age_seconds=previous.max_snapshot_age_seconds,
            currency_quantum_by_currency=previous.currency_quantum_by_currency,
        )
        result = persist_broker_current_position_valuation_run(
            copy, run=run, broker_snapshot=snapshot
        )
        saved = load_broker_current_position_valuation_run(
            copy, valuation_run_uid=run.run_uid
        )
        if (saved is None or saved.result_fingerprint
                != calculate_broker_current_position_result_fingerprint(run)
                or saved.position_count != run.position_count):
            raise ValueError("Disposable position read-back differs.")
        complete = (run.complete_portfolio_cost_basis_available
                    and run.complete_portfolio_market_value_available
                    and run.complete_portfolio_unrealized_pnl_available)
    return dict(contract_version=CONTRACT,
                status="copy_position_ready" if complete else "held_for_financial_review",
                position_count=run.position_count,
                cost_basis_available_count=run.cost_basis_available_count,
                market_value_available_count=run.market_value_available_count,
                unrealized_pnl_available_count=run.unrealized_pnl_available_count,
                snapshot_replayed=result.replayed,
                live_journal_written=False,
                financial_publication_authorized=False)
