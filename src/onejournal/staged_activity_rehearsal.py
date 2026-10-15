"""Connect a staged manual activity capture to the existing disposable journal path.

This deliberately has no live-write, broker, release, or service capability.
The current-position capture and safe live publication remain separate work.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import re

from onejournal.activity_financial_preview import (
    load_activity_financial_preview, report_preview, report_preview_csv,
)
from onejournal.activity_rehearsal import disposable_journal, prepare_copy
from onejournal.brokers.schwab.account_binding import (
    SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA, SchwabAccountPrivateBinding,
)
from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
from onejournal.journal.activity_refresh_repository import append_activity_copy
from onejournal.local_web import private_directory
from onejournal.manual_capture_upload import ManualCaptureIntake
from onejournal.provider_connectors.usage_policy import load_provider_usage_policy
from onejournal.refresh_activity import activity_plan, confirmed_import, review_activity
from onejournal.refresh_capture_authorization import load_private_capture_authorization
from onejournal.refresh_intake import acquisition_bundle, read_private


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CONTRACT = "onejournal.staged-activity-rehearsal.v1"


def rehearse_staged_activity(
    *, intake: ManualCaptureIntake, manifest_sha256: str, source_db: Path,
    asof: date, overlap_days: int, account_alias: str,
) -> dict[str, object]:
    """Revalidate saved bytes, then append and calculate on one temporary copy."""
    if not isinstance(manifest_sha256, str) or not _DIGEST.fullmatch(manifest_sha256):
        raise ValueError("A pinned staged manifest digest is required.")
    root = private_directory(intake.staging_root / manifest_sha256, "staged activity capture")
    manifest, responses = acquisition_bundle(root, response_count=2)
    receipt = intake.stage({"acquisition-manifest.json": manifest, **responses})
    if (not receipt["replayed"] or receipt["scope"] != "activity"
            or receipt["manifest_sha256"] != manifest_sha256):
        raise ValueError("The staged activity package or private approval changed.")
    authority = load_private_capture_authorization(
        intake.authorization_path, project_root=intake.project_root
    )
    private_binding = load_schwab_position_private_binding_bytes(
        read_private(intake.account_binding_path, 256 * 1024)
    )
    binding = SchwabAccountPrivateBinding(
        schema=SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
        connection_uid=private_binding.connection_uid,
        source_account_id=private_binding.source_account_id,
        provider_account_hash=private_binding.provider_account_hash,
        provider_account_number=private_binding.provider_account_number,
    )
    plan = activity_plan(confirmed_import(source_db, binding), binding,
                         asof=asof, overlap_days=overlap_days)
    capture = dict(
        binding=binding, asof=asof, overlap_days=overlap_days,
        expected_plan_sha256=plan["plan_sha256"], acquisition_root=root,
        acknowledgement=intake.acknowledgement_path, usage_policy=intake.usage_policy,
        expected_run_uid=authority.acquisition_run_uid,
        expected_approval_id=authority.acquisition_approval_id,
        expected_owner_uid=authority.owner_uid,
        expected_owner_epoch_uid=authority.owner_epoch_uid,
        evaluated_at=datetime.now(UTC),
    )
    review = review_activity(db=source_db, **capture)
    if review["status"] != "candidate_only":
        return dict(contract_version=CONTRACT, status="held_for_source_review",
                    new_records=0, live_journal_written=False,
                    disposable_copy_appended=False,
                    financial_publication_authorized=False)
    with disposable_journal(source_db) as copy:
        prepare_copy(copy)
        result = append_activity_copy(db=copy, **capture)
        preview = load_activity_financial_preview(
            copy, binding, expected_checkpoint_uid=result["import_uid"],
            account_alias=account_alias,
        )
        filters = dict(from_date=preview.coverage_start_date,
                       to_date=preview.coverage_end_date)
        report = report_preview(preview, **filters)
        # Exercise the same CSV projection the website uses; no value is logged.
        report_preview_csv(preview, **filters)
        counts = report["counts"]
        return dict(contract_version=CONTRACT,
                    status="copy_financial_preview_complete",
                    new_records=result["new_records"],
                    report_quality=report["metadata"]["quality"],
                    available_count=counts["available_count"],
                    unavailable_count=counts["unavailable_count"],
                    reconciliation_pending_count=counts["reconciliation_pending_count"],
                    fresh_position_snapshot_required=(
                        preview.position_snapshot_utc < preview.checkpoint_utc
                    ),
                    live_journal_written=False, disposable_copy_appended=True,
                    financial_publication_authorized=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("db", "authorization", "acknowledgement", "position-binding",
                 "usage-policy", "staging-root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--asof", required=True, type=date.fromisoformat)
    parser.add_argument("--overlap-days", required=True, type=int)
    parser.add_argument("--account-alias", required=True)
    args = parser.parse_args(argv)
    try:
        project_root = Path(__file__).resolve().parents[2]
        intake = ManualCaptureIntake(
            authorization_path=args.authorization,
            acknowledgement_path=args.acknowledgement,
            account_binding_path=args.position_binding,
            usage_policy=load_provider_usage_policy(args.usage_policy),
            staging_root=args.staging_root, project_root=project_root,
        )
        result = rehearse_staged_activity(
            intake=intake, manifest_sha256=args.manifest_sha256,
            source_db=args.db, asof=args.asof,
            overlap_days=args.overlap_days, account_alias=args.account_alias,
        )
        print(json.dumps(result, sort_keys=True))
        return 2 if result["status"] == "held_for_source_review" else 0
    except Exception:
        print("Staged activity rehearsal stopped. Check the private capture, approval, active journal and account identity. No broker request, live journal write or publication was attempted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
