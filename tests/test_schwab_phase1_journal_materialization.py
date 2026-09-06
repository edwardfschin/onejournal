from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest

import duckdb

from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_assembly import (
    _family,
    calculate_schwab_evidence_assembly_fingerprint,
    schwab_phase1_evidence_assembly_bytes,
)
from onejournal.journal.schwab_evidence_import_repository import (
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (
    build_schwab_journal_materialization_plan,
    persist_schwab_journal_materialization,
    privacy_safe_materialization_audit,
)
from scripts.journal.materialize_schwab_phase1_journal import main as operator_main
from tests.test_schwab_phase1_evidence_import import (
    ACCOUNT_UID,
    MIGRATIONS_DIR,
    synthetic_assembly,
)


def _unmatched_close_assembly():
    assembly = synthetic_assembly()
    families = list(assembly.families)
    index = next(i for i, family in enumerate(families) if family.family == "fills")
    original = families[index]
    record = dict(original.records[0])
    record["side"] = "sell"
    record["open_close"] = "close"
    families[index] = _family(
        "fills",
        source_manifest_sha256s=original.source_manifest_sha256s,
        source_raw_sha256s=original.source_raw_sha256s,
        source_record_count=1,
        records=(MappingProxyType(record),),
    )
    candidate = replace(
        assembly,
        assembly_uid="pending",
        families=tuple(families),
        result_fingerprint="pending",
    )
    fingerprint = calculate_schwab_evidence_assembly_fingerprint(candidate)
    return replace(
        candidate,
        assembly_uid=f"schwab-evidence-assembly:{fingerprint}",
        result_fingerprint=fingerprint,
    )


class SchwabPhase1JournalMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "journal.duckdb"
        apply_schema_migrations(self.db_path, migrations_dir=MIGRATIONS_DIR)
        self.db_path.chmod(0o600)

    def test_atomic_materialization_replay_and_exact_lineage(self) -> None:
        assembly = synthetic_assembly()
        persist_schwab_phase1_evidence_assembly(self.db_path, assembly)

        first = persist_schwab_journal_materialization(
            self.db_path,
            assembly,
            materialized_at=datetime(2026, 9, 6, 1, 0, tzinfo=UTC),
        )
        replay = persist_schwab_journal_materialization(self.db_path, assembly)

        self.assertTrue(first.created)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.materialization_uid, replay.materialization_uid)
        self.assertEqual(first.fill_count, 1)
        self.assertEqual(first.episode_count, 1)
        self.assertEqual(first.final_status, "ready")
        self.assertNotIn(ACCOUNT_UID, first.materialization_uid)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM normalized_fills").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM trade_episodes").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM trade_episode_legs").fetchone()[0], 1)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM phase1_journal_materialization_runs").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM phase1_journal_materialized_episode_fills").fetchone()[0],
                1,
            )

    def test_incomplete_history_remains_visible_but_financially_unavailable(self) -> None:
        assembly = _unmatched_close_assembly()
        plan = build_schwab_journal_materialization_plan(assembly)
        self.assertEqual(plan.review_required_scope_count, 1)
        self.assertEqual(plan.review_required_fill_count, 1)
        self.assertEqual(plan.final_status, "review_required")
        self.assertEqual(plan.episodes[0].reason_code, "history_extension_required")
        self.assertNotIn(ACCOUNT_UID, plan.episodes[0].preview.episode_uid)
        persist_schwab_phase1_evidence_assembly(self.db_path, assembly)
        persist_schwab_journal_materialization(self.db_path, assembly)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT e.status, e.net_quantity, e.gross_cashflow, e.commission,
                       e.fees, m.lifecycle_quality, m.reason_code
                FROM trade_episodes e
                JOIN phase1_journal_materialized_episodes m USING (episode_uid)
                """
            ).fetchone()
        self.assertEqual(
            row,
            (
                "review_required",
                None,
                None,
                None,
                None,
                "review_required",
                "history_extension_required",
            ),
        )

    def test_operator_requires_private_files_and_emits_value_free_audit(self) -> None:
        assembly = synthetic_assembly()
        artifact_path = self.root / "assembly.json"
        artifact_path.write_bytes(schwab_phase1_evidence_assembly_bytes(assembly))
        artifact_path.chmod(0o600)
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = operator_main(
                ["--assembly", str(artifact_path), "--db", str(self.db_path)]
            )
        self.assertEqual(result, 0)
        audit = json.loads(stdout.getvalue())
        self.assertEqual(audit["operation"], "materialized")
        self.assertNotIn("AAPL", stdout.getvalue())
        self.assertNotIn(ACCOUNT_UID, stdout.getvalue())
        self.assertEqual(audit["fill_count"], 1)

    def test_replay_rejects_changed_materialization_lineage(self) -> None:
        assembly = synthetic_assembly()
        persist_schwab_phase1_evidence_assembly(self.db_path, assembly)
        result = persist_schwab_journal_materialization(self.db_path, assembly)
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                UPDATE phase1_journal_materialization_runs
                SET final_status = 'review_required'
                WHERE materialization_uid = ?
                """,
                [result.materialization_uid],
            )
        with self.assertRaisesRegex(ValueError, "stored run differs"):
            persist_schwab_journal_materialization(self.db_path, assembly)

    def test_replay_rejects_changed_normalized_economics(self) -> None:
        assembly = synthetic_assembly()
        persist_schwab_phase1_evidence_assembly(self.db_path, assembly)
        persist_schwab_journal_materialization(self.db_path, assembly)
        with duckdb.connect(str(self.db_path)) as con:
            con.execute("UPDATE normalized_fills SET fill_price = fill_price + 1")
        with self.assertRaisesRegex(ValueError, "normalized fills differ"):
            persist_schwab_journal_materialization(self.db_path, assembly)

    def test_materialization_requires_exact_assembly_already_in_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact Schwab evidence assembly"):
            persist_schwab_journal_materialization(
                self.db_path,
                synthetic_assembly(),
            )


if __name__ == "__main__":
    unittest.main()
