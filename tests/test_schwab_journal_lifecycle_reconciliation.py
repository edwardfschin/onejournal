from __future__ import annotations

from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    _family,
    calculate_schwab_evidence_assembly_fingerprint,
    schwab_phase1_evidence_assembly_bytes,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_import_repository import (
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (
    persist_schwab_journal_materialization,
)
from onejournal.journal.schwab_evidence_v2_repository import (
    load_schwab_phase1_evidence_assembly_v2,
    persist_schwab_journal_lifecycle_reconciliation,
    persist_schwab_phase1_evidence_assembly_v2,
)
from onejournal.journal.schwab_journal_lifecycle_reconciliation import (
    build_schwab_journal_lifecycle_reconciliation,
)
from tests.test_schwab_phase1_evidence_import import ASOF, synthetic_assembly
from scripts.journal.reconcile_schwab_phase1_journal_lifecycle import (
    main as operator_main,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


def option_assembly(
    *,
    with_expiration: bool,
    version: str = SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
):
    assembly = synthetic_assembly(
        lifecycle_expiration=with_expiration,
        assembly_version=version,
    )
    families = list(assembly.families)
    index = next(i for i, family in enumerate(families) if family.family == "fills")
    prior = families[index]
    record = dict(prior.records[0])
    record.update(
        {
            "asset_class": "option",
            "symbol": "AAPL",
            "side": "buy",
            "option_symbol": "AAPL  260904C00200000",
            "underlying_symbol": "AAPL",
            "option_type": "CALL",
            "expiry": ASOF.isoformat(),
            "strike": "200",
            "multiplier": "100",
            "open_close": "open",
        }
    )
    families[index] = _family(
        "fills",
        source_manifest_sha256s=prior.source_manifest_sha256s,
        source_raw_sha256s=prior.source_raw_sha256s,
        source_record_count=1,
        records=(record,),
    )
    candidate = replace(
        assembly,
        assembly_uid="pending",
        result_fingerprint="pending",
        families=tuple(families),
        final_status=(
            "review_required"
            if with_expiration and version == SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
            else "ready"
        ),
    )
    fingerprint = calculate_schwab_evidence_assembly_fingerprint(candidate)
    return replace(
        candidate,
        assembly_uid=f"schwab-evidence-assembly:{fingerprint}",
        result_fingerprint=fingerprint,
    )


class SchwabJournalLifecycleReconciliationTests(unittest.TestCase):
    def test_terminal_expiration_closes_episode_but_withholds_financial_authority(self) -> None:
        plan = build_schwab_journal_lifecycle_reconciliation(
            option_assembly(with_expiration=True)
        )

        self.assertEqual(plan.closed_count, 1)
        self.assertEqual(plan.open_count, 0)
        self.assertEqual(plan.review_required_count, 0)
        self.assertEqual(plan.final_status, "review_required")
        self.assertEqual(plan.matched_terminal_event_leg_count, 1)
        state = plan.states[0]
        self.assertEqual(state.prior_status, "open")
        self.assertEqual(state.reconciled_status, "closed")
        self.assertEqual(state.lifecycle_quality, "review_required")
        self.assertEqual(state.reason_code, "broker_terminal_event_review_required")
        self.assertEqual(
            state.position_reconciliation_status, "terminal_reconciled"
        )

    def test_complete_position_absence_never_remains_labelled_open(self) -> None:
        plan = build_schwab_journal_lifecycle_reconciliation(
            option_assembly(with_expiration=False)
        )

        self.assertEqual(plan.closed_count, 0)
        self.assertEqual(plan.open_count, 0)
        self.assertEqual(plan.review_required_count, 1)
        state = plan.states[0]
        self.assertEqual(state.prior_status, "open")
        self.assertEqual(state.reconciled_status, "review_required")
        self.assertEqual(
            state.reason_code,
            "current_position_absent_closure_evidence_required",
        )

    def test_v1_cannot_enter_lifecycle_reconciliation(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires assembly v2"):
            build_schwab_journal_lifecycle_reconciliation(synthetic_assembly())

    def test_additive_v2_persistence_preserves_v1_materialization(self) -> None:
        v1 = option_assembly(
            with_expiration=True,
            version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
        )
        v2 = option_assembly(with_expiration=True)
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / "journal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            persist_schwab_phase1_evidence_assembly(db_path, v1)
            materialized = persist_schwab_journal_materialization(db_path, v1)

            first = persist_schwab_phase1_evidence_assembly_v2(db_path, v2)
            replay = persist_schwab_phase1_evidence_assembly_v2(db_path, v2)
            loaded = load_schwab_phase1_evidence_assembly_v2(
                db_path, assembly_uid=v2.assembly_uid
            )
            plan = persist_schwab_journal_lifecycle_reconciliation(db_path, v2)
            repeated = persist_schwab_journal_lifecycle_reconciliation(db_path, v2)

            self.assertTrue(first.created)
            self.assertTrue(replay.replayed)
            self.assertEqual(loaded, v2)
            self.assertEqual(plan, repeated)
            self.assertEqual(plan.closed_count, 1)
            with duckdb.connect(str(db_path), read_only=True) as con:
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM trade_episodes").fetchone()[0],
                    materialized.episode_count,
                )
                self.assertEqual(
                    con.execute(
                        "SELECT status FROM trade_episodes"
                    ).fetchone()[0],
                    "open",
                )
                self.assertEqual(
                    con.execute(
                        "SELECT reconciled_status FROM phase1_journal_episode_lifecycle_states"
                    ).fetchone()[0],
                    "closed",
                )

    def test_operator_is_private_replay_safe_and_provider_free(self) -> None:
        v1 = option_assembly(
            with_expiration=True,
            version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
        )
        v2 = option_assembly(with_expiration=True)
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            db_path = root / "journal.duckdb"
            artifact_path = root / "assembly-v2.json"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            db_path.chmod(0o600)
            persist_schwab_phase1_evidence_assembly(db_path, v1)
            persist_schwab_journal_materialization(db_path, v1)
            artifact_path.write_bytes(schwab_phase1_evidence_assembly_bytes(v2))
            artifact_path.chmod(0o600)

            first_stdout = StringIO()
            with redirect_stdout(first_stdout):
                first = operator_main(
                    ["--assembly", str(artifact_path), "--db", str(db_path)]
                )
            replay_stdout = StringIO()
            with redirect_stdout(replay_stdout):
                replay = operator_main(
                    ["--assembly", str(artifact_path), "--db", str(db_path)]
                )

            self.assertEqual((first, replay), (0, 0))
            self.assertEqual(json.loads(first_stdout.getvalue())["evidence_operation"], "persisted")
            self.assertEqual(json.loads(replay_stdout.getvalue())["evidence_operation"], "replayed")
            self.assertNotIn("AAPL", first_stdout.getvalue())
            self.assertNotIn("account", first_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
