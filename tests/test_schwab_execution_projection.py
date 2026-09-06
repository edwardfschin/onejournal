from __future__ import annotations

from contextlib import redirect_stdout
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from fastapi.testclient import TestClient

from onejournal.api.local_owner_journal import create_local_owner_journal_app
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
)
from onejournal.journal.schwab_evidence_import_repository import (
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (
    persist_schwab_journal_materialization,
)
from onejournal.journal.schwab_execution_projection import (
    ProjectedInstrument,
    _strategy,
    persist_schwab_execution_projection,
)
from onejournal.journal.schwab_evidence_v2_repository import (
    persist_schwab_journal_lifecycle_reconciliation,
    persist_schwab_phase1_evidence_assembly_v2,
)
from scripts.journal.project_schwab_phase1_executions import main as operator_main
from tests.test_schwab_phase1_evidence_import import MIGRATIONS_DIR, synthetic_assembly


def _instrument(*, execution_count: int = 2) -> ProjectedInstrument:
    return ProjectedInstrument(
        episode_uid="episode-1",
        instrument_index=1,
        instrument_uid="instrument-1",
        asset_class="option",
        symbol="AAPL  260918C00100000",
        underlying_symbol="AAPL",
        option_type="CALL",
        expiry=date(2026, 9, 18),
        strike=Decimal("100"),
        multiplier=Decimal("100"),
        currency="USD",
        opening_direction="LONG",
        execution_count=execution_count,
        buy_quantity=Decimal("1"),
        sell_quantity=Decimal("1"),
        captured_quantity_delta=Decimal("0"),
        instrument_projection_fingerprint="a" * 64,
    )


class SchwabExecutionProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "journal.duckdb"
        apply_schema_migrations(self.db_path, migrations_dir=MIGRATIONS_DIR)
        self.db_path.chmod(0o600)
        self.assembly = synthetic_assembly()
        persist_schwab_phase1_evidence_assembly(self.db_path, self.assembly)
        self.materialization = persist_schwab_journal_materialization(
            self.db_path,
            self.assembly,
        )

    def test_single_instrument_round_trip_never_becomes_a_vertical(self) -> None:
        instrument = _instrument()
        fills = {
            instrument.instrument_uid: [
                {"episode_group_id": "", "open_close": "OPEN"},
                {"episode_group_id": "", "open_close": "CLOSE"},
            ]
        }
        self.assertEqual(
            _strategy([instrument], fills, lifecycle_quality="resolved"),
            ("buy_call", "Buy Call"),
        )

    def test_local_api_rejects_materialized_state_without_projection(self) -> None:
        with self.assertRaisesRegex(ValueError, "execution-first projection"):
            create_local_owner_journal_app(journal_db_path=self.db_path)

    def test_projection_persists_replays_and_reconciles_exact_schwab_cash(self) -> None:
        first = persist_schwab_execution_projection(
            self.db_path,
            materialization_uid=self.materialization.materialization_uid,
            projected_at=datetime(2026, 9, 6, 3, 0, tzinfo=UTC),
        )
        replay = persist_schwab_execution_projection(
            self.db_path,
            materialization_uid=self.materialization.materialization_uid,
        )
        self.assertTrue(first.created)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.execution_count, 1)
        self.assertEqual(first.schwab_net_amount_match_count, 1)
        self.assertEqual(first.schwab_net_amount_mismatch_count, 0)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            episode = con.execute(
                """
                SELECT strategy_type, strategy_label, instrument_count,
                       execution_count, instrument_summary
                FROM phase1_journal_projected_episodes
                """
            ).fetchone()
            execution = con.execute(
                """
                SELECT schwab_net_cash_movement,
                       calculated_net_cash_movement, net_amount_reconciled
                FROM phase1_journal_projected_executions
                """
            ).fetchone()
        self.assertEqual(episode, ("stock_long", "Stock Long", 1, 1, "Equity"))
        self.assertEqual(execution, (Decimal("-200"), Decimal("-200"), True))

        lifecycle_assembly = synthetic_assembly(
            assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
        )
        persist_schwab_phase1_evidence_assembly_v2(
            self.db_path, lifecycle_assembly
        )
        persist_schwab_journal_lifecycle_reconciliation(
            self.db_path, lifecycle_assembly
        )
        client = TestClient(create_local_owner_journal_app(journal_db_path=self.db_path))
        search = client.get("/api/v5/local-owner/journal/search")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(
            search.json()["metadata"]["contract_version"],
            "onejournal.local-owner-journal.v5",
        )
        episode_uid = search.json()["episodes"][0]["episode_uid"]
        lifecycle = client.get(f"/api/v5/local-owner/journal/trades/{episode_uid}")
        self.assertEqual(lifecycle.status_code, 200)
        self.assertEqual(lifecycle.json()["trade"]["execution_count"], 1)
        self.assertEqual(lifecycle.json()["trade"]["instrument_count"], 1)
        self.assertEqual(lifecycle.json()["trade"]["asset_class"], "stock")
        self.assertEqual(
            lifecycle.json()["trade"]["position_reconciliation_status"],
            "matched_current",
        )
        self.assertEqual(len(lifecycle.json()["instruments"]), 1)
        self.assertEqual(len(lifecycle.json()["executions"]), 1)
        self.assertEqual(
            lifecycle.json()["executions"][0]["reconciliation_status"],
            "matched_schwab_transaction",
        )
        self.assertNotIn("source_fill_id", repr(lifecycle.json()))

    def test_projection_fails_closed_when_schwab_net_amount_does_not_match(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            raw = con.execute(
                """
                SELECT records_json FROM phase1_schwab_evidence_import_families
                WHERE family = 'transactions'
                """
            ).fetchone()[0]
            records = json.loads(raw)
            records[0]["net_amount"] = "-199"
            con.execute(
                """
                UPDATE phase1_schwab_evidence_import_families
                SET records_json = ? WHERE family = 'transactions'
                """,
                [json.dumps(records, sort_keys=True, separators=(",", ":"))],
            )
        with self.assertRaisesRegex(ValueError, "differs from Schwab net_amount"):
            persist_schwab_execution_projection(
                self.db_path,
                materialization_uid=self.materialization.materialization_uid,
            )

    def test_operator_is_exact_private_and_value_free(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = operator_main(
                [
                    "--db", str(self.db_path),
                    "--materialization-uid", self.materialization.materialization_uid,
                ]
            )
        self.assertEqual(result, 0)
        audit = json.loads(stdout.getvalue())
        self.assertEqual(audit["operation"], "projected")
        self.assertEqual(audit["schwab_net_amount_mismatch_count"], 0)
        self.assertNotIn("AAPL", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
