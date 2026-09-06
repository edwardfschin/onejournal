from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.domain import create_entry, save_review
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION,
)
from onejournal.journal.schwab_evidence_import_repository import (
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (
    persist_schwab_journal_materialization,
)
from onejournal.journal.schwab_evidence_v2_repository import (
    persist_schwab_journal_lifecycle_reconciliation,
    persist_schwab_phase1_evidence_assembly_v2,
)
from onejournal.journal.schwab_execution_projection import (
    build_schwab_execution_projection_from_assembly,
    build_schwab_execution_projection_plan,
    persist_schwab_execution_projection,
)
from onejournal.journal.schwab_history_revision import (
    activate_prior_history_revision,
    persist_schwab_history_revision,
)
from onejournal.journal.search import JournalSearchFilters, search_journal
from tests.test_schwab_phase1_evidence_import import synthetic_assembly


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


class SchwabHistoryRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        apply_schema_migrations(self.db_path, migrations_dir=MIGRATIONS_DIR)
        self.db_path.chmod(0o600)

        self.v1 = synthetic_assembly(
            assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION
        )
        persist_schwab_phase1_evidence_assembly(self.db_path, self.v1)
        self.legacy = persist_schwab_journal_materialization(
            self.db_path, self.v1
        )
        persist_schwab_execution_projection(
            self.db_path, materialization_uid=self.legacy.materialization_uid
        )
        self.v2 = synthetic_assembly(
            assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
        )
        persist_schwab_phase1_evidence_assembly_v2(self.db_path, self.v2)
        persist_schwab_journal_lifecycle_reconciliation(self.db_path, self.v2)

    def test_revision_is_append_only_current_and_exactly_replayable(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            episode_uid = str(
                con.execute("SELECT episode_uid FROM trade_episodes").fetchone()[0]
            )
            save_review(
                con,
                episode_uid=episode_uid,
                review_status="reviewed",
                setup_quality="good",
                source="api",
            )
            create_entry(
                con,
                episode_uid=episode_uid,
                entry_type="note",
                body="private test note",
                created_source="api",
            )

        first = persist_schwab_history_revision(
            self.db_path,
            self.v2,
            predecessor_materialization_uid=self.legacy.materialization_uid,
            created_at=datetime(2026, 9, 7, 1, 0, tzinfo=UTC),
        )
        replay = persist_schwab_history_revision(
            self.db_path,
            self.v2,
            predecessor_materialization_uid=self.legacy.materialization_uid,
        )

        self.assertTrue(first.created)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.activation_sequence, 2)
        self.assertEqual(first.new_fill_count, 0)
        self.assertEqual(first.reused_fill_count, 1)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM phase1_journal_history_revisions"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM phase1_journal_history_revision_activations"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM trade_episodes").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM journal_current_trade_episodes"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM journal_current_projected_executions"
                ).fetchone()[0],
                1,
            )
            result = search_journal(con, JournalSearchFilters())
            self.assertEqual(len(result.episodes), 1)
            self.assertEqual(result.episodes[0]["review_status"], "reviewed")
            self.assertEqual(len(result.entries), 1)

    def test_projection_builder_is_identical_without_database_staging(self) -> None:
        from_database = build_schwab_execution_projection_plan(
            self.db_path,
            materialization_uid=self.legacy.materialization_uid,
        )
        from_assembly = build_schwab_execution_projection_from_assembly(self.v1)
        self.assertEqual(from_assembly, from_database)

    def test_rollback_appends_activation_and_preserves_both_snapshots(self) -> None:
        current = persist_schwab_history_revision(
            self.db_path,
            self.v2,
            predecessor_materialization_uid=self.legacy.materialization_uid,
        )
        activation_uid = activate_prior_history_revision(
            self.db_path,
            revision_uid=str(current.predecessor_revision_uid),
            activated_at=datetime(2026, 9, 7, 2, 0, tzinfo=UTC),
        )
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            active = con.execute(
                """
                SELECT revision_uid, activation_sequence, activation_reason
                FROM phase1_journal_history_revision_activations
                WHERE activation_uid = ?
                """,
                [activation_uid],
            ).fetchone()
            self.assertEqual(active[0], current.predecessor_revision_uid)
            self.assertEqual(active[1:], (3, "rollback"))
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM phase1_journal_history_revisions"
                ).fetchone()[0],
                2,
            )

    def test_wrong_predecessor_fails_without_partial_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "predecessor materialization"):
            persist_schwab_history_revision(
                self.db_path,
                self.v2,
                predecessor_materialization_uid="missing",
            )
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM phase1_journal_history_revisions"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
