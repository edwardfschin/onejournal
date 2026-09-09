from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import duckdb

from onejournal.journal.migrations import (
    BASELINE_TABLE_DEFINITIONS,
    apply_schema_migrations,
)
from scripts.journal.init_journal_db import init_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"
MIGRATION_0002_RELEASED_CHECKSUM = (
    "523b5614334f32e2fd41783b58b0eac974456348613bb612ac0c2befc7524ba4"
)


class JournalMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "onejournal.duckdb"

    def test_init_schema_creates_ledger_and_baseline_tables(self) -> None:
        apply_schema_migrations(self.db_path, migrations_dir=MIGRATIONS_DIR)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
            self.assertIn("schema_migrations", tables)
            self.assertIn("import_runs", tables)
            self.assertIn("normalized_fills", tables)
            self.assertIn("manual_reviews", tables)
            self.assertIn("trade_episodes", tables)
            self.assertIn("trade_episode_legs", tables)
            self.assertIn("normalized_accounts", tables)
            self.assertIn("normalized_orders", tables)
            self.assertIn("normalized_positions", tables)
            self.assertIn("normalized_transactions", tables)
            self.assertIn("normalized_lifecycle_events", tables)
            self.assertIn("normalized_lifecycle_event_legs", tables)
            self.assertIn("approved_option_lifecycle_events", tables)
            self.assertIn("approved_option_lifecycle_predecessors", tables)
            self.assertIn("approved_option_lifecycle_source_legs", tables)
            self.assertIn("pnl_calculation_runs", tables)
            self.assertIn("pnl_group_results", tables)
            self.assertIn("pnl_closed_lot_allocations", tables)
            self.assertIn("pnl_lifecycle_allocations", tables)
            self.assertIn("market_quote_ingestion_runs", tables)
            self.assertIn("normalized_market_quotes", tables)
            self.assertIn("broker_position_snapshot_runs", tables)
            self.assertIn("broker_position_snapshot_records", tables)
            self.assertIn("pnl_position_valuation_runs", tables)
            self.assertIn("pnl_canonical_position_valuations", tables)
            self.assertIn("pnl_bounded_valuation_runs", tables)
            self.assertIn("pnl_bounded_position_valuations", tables)
            self.assertIn("pnl_bounded_valuation_subtotals", tables)
            self.assertIn("pnl_broker_current_valuation_runs", tables)
            self.assertIn("pnl_broker_current_position_valuations", tables)
            self.assertIn("pnl_broker_current_portfolio_totals", tables)
            self.assertIn("phase1_schwab_evidence_import_runs", tables)
            self.assertIn("phase1_schwab_evidence_import_families", tables)
            self.assertIn("journal_entries", tables)
            self.assertIn("journal_entry_revisions", tables)
            self.assertIn("journal_reviews", tables)
            self.assertIn("journal_strategies", tables)
            self.assertIn("journal_tags", tables)
            self.assertIn("journal_entry_tag_events", tables)
            self.assertIn("journal_attachments", tables)
            self.assertIn("journal_saved_views", tables)
            self.assertIn("journal_goals", tables)
            self.assertIn("journal_goal_checkins", tables)
            self.assertIn("journal_habits", tables)
            self.assertIn("journal_habit_events", tables)
            self.assertIn("journal_review_period_events", tables)
            self.assertIn("local_owner_api_audit_events", tables)
            self.assertIn("local_owner_api_operation_receipts", tables)
            self.assertIn("local_owner_financial_api_audit_events", tables)
            self.assertIn("phase1_journal_materialization_runs", tables)
            self.assertIn("phase1_journal_materialized_fills", tables)
            self.assertIn("phase1_journal_materialized_episodes", tables)
            self.assertIn("phase1_journal_materialized_episode_fills", tables)
            self.assertIn("phase1_journal_execution_projection_runs", tables)
            self.assertIn("phase1_journal_projected_episodes", tables)
            self.assertIn("phase1_journal_projected_instruments", tables)
            self.assertIn("phase1_journal_projected_executions", tables)
            self.assertIn("phase1_schwab_evidence_v2_import_runs", tables)
            self.assertIn("phase1_schwab_evidence_v2_import_families", tables)
            self.assertIn("phase1_journal_lifecycle_reconciliation_runs", tables)
            self.assertIn("phase1_journal_episode_lifecycle_states", tables)
            self.assertIn("phase1_journal_history_revisions", tables)
            self.assertIn("phase1_journal_history_revision_episodes", tables)
            self.assertIn("phase1_journal_history_revision_activations", tables)
            self.assertIn("journal_current_trade_episodes", tables)
            self.assertIn("phase1_reporting_releases", tables)
            self.assertIn("phase1_reporting_release_accounts", tables)
            self.assertIn("phase1_reporting_release_realized_items", tables)
            self.assertIn("phase1_reporting_release_omissions", tables)
            self.assertIn("phase1_reporting_api_audit_events", tables)

            rows = con.execute("SELECT version, status FROM schema_migrations ORDER BY version").fetchall()
            self.assertEqual(rows[0][0], "0001")
            self.assertEqual(rows[0][1], "applied")
            self.assertEqual(rows[1][0], "0002")
            self.assertEqual(rows[1][1], "applied")
            self.assertEqual(rows[2][0], "0003")
            self.assertEqual(rows[2][1], "applied")
            self.assertEqual(rows[3][0], "0004")
            self.assertEqual(rows[3][1], "applied")
            self.assertEqual(rows[4][0], "0005")
            self.assertEqual(rows[4][1], "applied")
            self.assertEqual(rows[5][0], "0006")
            self.assertEqual(rows[5][1], "applied")
            self.assertEqual(rows[6][0], "0007")
            self.assertEqual(rows[6][1], "applied")
            self.assertEqual(rows[7][0], "0008")
            self.assertEqual(rows[7][1], "applied")
            self.assertEqual(rows[8][0], "0009")
            self.assertEqual(rows[8][1], "applied")
            self.assertEqual(rows[9][0], "0010")
            self.assertEqual(rows[9][1], "applied")
            self.assertEqual(rows[10][0], "0011")
            self.assertEqual(rows[10][1], "applied")
            self.assertEqual(rows[11][0], "0012")
            self.assertEqual(rows[11][1], "applied")
            self.assertEqual(rows[12][0], "0013")
            self.assertEqual(rows[12][1], "applied")
            self.assertEqual(rows[13][0], "0014")
            self.assertEqual(rows[13][1], "applied")
            self.assertEqual(rows[14][0], "0015")
            self.assertEqual(rows[14][1], "applied")
            self.assertEqual(rows[15][0], "0016")
            self.assertEqual(rows[15][1], "applied")
            self.assertEqual(rows[16][0], "0017")
            self.assertEqual(rows[16][1], "applied")
            self.assertEqual(rows[17][0], "0018")
            self.assertEqual(rows[17][1], "applied")
            self.assertEqual(rows[18][0], "0019")
            self.assertEqual(rows[18][1], "applied")
            self.assertEqual(rows[19][0], "0020")
            self.assertEqual(rows[19][1], "applied")
            self.assertEqual(rows[20][0], "0021")
            self.assertEqual(rows[20][1], "applied")
            self.assertEqual(rows[21][0], "0022")
            self.assertEqual(rows[21][1], "applied")
            self.assertEqual(rows[22][0], "0023")
            self.assertEqual(rows[22][1], "applied")
            self.assertEqual(rows[23][0], "0024")
            self.assertEqual(rows[23][1], "applied")
            self.assertEqual(rows[24][0], "0025")
            self.assertEqual(rows[24][1], "applied")
            self.assertEqual(rows[25][0], "0026")
            self.assertEqual(rows[25][1], "applied")

            fill_columns = {
                row[1]: row[2]
                for row in con.execute("PRAGMA table_info(normalized_fills)").fetchall()
            }
            self.assertEqual(fill_columns["filled_at_utc"], "VARCHAR")
            self.assertEqual(fill_columns["fetched_at_utc"], "VARCHAR")
            lifecycle_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(normalized_lifecycle_events)"
                ).fetchall()
            }
            self.assertEqual(lifecycle_columns["event_at_utc"], "VARCHAR")
            quote_run_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(market_quote_ingestion_runs)"
                ).fetchall()
            }
            self.assertEqual(quote_run_columns["ingestion_contract_version"], "VARCHAR")
            self.assertEqual(quote_run_columns["source_locator"], "VARCHAR")
            position_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(broker_position_snapshot_records)"
                ).fetchall()
            }
            self.assertEqual(
                position_columns["broker_tax_lot_average_price"],
                "DECIMAL(38,13)",
            )
            reporting_columns = {
                row[1]: (row[2], row[3])
                for row in con.execute(
                    "PRAGMA table_info(phase1_reporting_releases)"
                ).fetchall()
            }
            self.assertEqual(
                reporting_columns["current_owner_acceptance_uid"],
                ("VARCHAR", True),
            )
            self.assertEqual(
                reporting_columns["current_owner_accepted_at_utc"],
                ("VARCHAR", True),
            )
            self.assertEqual(
                reporting_columns["realized_owner_acceptance_uid"],
                ("VARCHAR", True),
            )
            self.assertEqual(
                reporting_columns["realized_owner_accepted_at_utc"],
                ("VARCHAR", True),
            )
            realized_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(phase1_reporting_release_realized_items)"
                ).fetchall()
            }
            self.assertEqual(realized_columns["realized_pnl"], "DECIMAL(38,27)")

    def test_released_migration_0002_checksum_is_immutable(self) -> None:
        migration_path = (
            MIGRATIONS_DIR
            / "0002_add_normalized_accounts_orders_positions_transactions.sql"
        )
        self.assertEqual(
            sha256(migration_path.read_bytes()).hexdigest(),
            MIGRATION_0002_RELEASED_CHECKSUM,
        )

    def test_migration_0023_preserves_existing_broker_current_values(self) -> None:
        apply_schema_migrations(
            self.db_path,
            target_version="0022",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """INSERT INTO broker_position_snapshot_records (
                       snapshot_uid, instrument_key, asset_class, market_scope,
                       currency, symbol, quantity, broker_average_cost,
                       broker_unrealized_pnl, broker_tax_lot_average_price
                   ) VALUES (
                       'snapshot-1', 'instrument-1', 'equity', 'US', 'USD',
                       'TEST', 1, 12.3456789012, 3.4567890123, 12.3456789012
                   )"""
            )
            con.execute(
                """INSERT INTO pnl_broker_current_position_valuations (
                       valuation_run_uid, instrument_key, asset_class,
                       market_scope, currency, symbol, quantity,
                       tax_lot_average_price, open_cost_basis,
                       broker_reported_unrealized_pnl, unrealized_pnl,
                       unrealized_reconciliation_difference, cost_basis_status,
                       market_value_status, unrealized_pnl_status,
                       position_status, reason_codes_json
                   ) VALUES (
                       'run-1', 'instrument-1', 'equity', 'US', 'USD', 'TEST',
                       1, 12.3456789012, 12.3456789012, 3.4567890123,
                       3.4567890123, 0.0000000001, 'available', 'available',
                       'available', 'available', '[]'
                   )"""
            )
            con.execute(
                """INSERT INTO pnl_broker_current_portfolio_totals
                   VALUES ('run-1', 'USD', 12.3456789012, 15.80, 3.4567890123)"""
            )

        resulting_version = apply_schema_migrations(
            self.db_path,
            migrations_dir=MIGRATIONS_DIR,
        )
        self.assertEqual(resulting_version, 26)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            snapshot_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(broker_position_snapshot_records)"
                ).fetchall()
            }
            valuation_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(pnl_broker_current_position_valuations)"
                ).fetchall()
            }
            total_columns = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(pnl_broker_current_portfolio_totals)"
                ).fetchall()
            }
            self.assertEqual(
                snapshot_columns["broker_tax_lot_average_price"],
                "DECIMAL(38,13)",
            )
            self.assertEqual(
                valuation_columns["unrealized_reconciliation_difference"],
                "DECIMAL(38,13)",
            )
            self.assertEqual(
                total_columns["portfolio_unrealized_pnl"],
                "DECIMAL(38,13)",
            )
            self.assertEqual(
                con.execute(
                    """SELECT broker_average_cost, broker_unrealized_pnl,
                              broker_tax_lot_average_price
                       FROM broker_position_snapshot_records"""
                ).fetchone(),
                (
                    Decimal("12.3456789012000"),
                    Decimal("3.4567890123000"),
                    Decimal("12.3456789012000"),
                ),
            )

    def test_migration_0025_preserves_audit_rows_and_requires_empty_releases(
        self,
    ) -> None:
        apply_schema_migrations(
            self.db_path,
            target_version="0024",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """INSERT INTO phase1_reporting_api_audit_events VALUES (
                       'audit-1', 'realized_history', NULL, ?, '{}',
                       0, 0, 0, 0, 'unavailable',
                       '2026-09-09T00:00:00Z'
                   )""",
                ["a" * 64],
            )

        self.assertEqual(
            apply_schema_migrations(
                self.db_path,
                target_version="0025",
                migrations_dir=MIGRATIONS_DIR,
            ),
            25,
        )
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(
                con.execute(
                    "SELECT audit_uid FROM phase1_reporting_api_audit_events"
                ).fetchall(),
                [("audit-1",)],
            )

        blocked_path = Path(self.tmp.name) / "blocked.duckdb"
        apply_schema_migrations(
            blocked_path,
            target_version="0024",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(blocked_path)) as con:
            con.execute(
                """INSERT INTO phase1_reporting_releases VALUES (
                       'release-1',
                       'onejournal.phase1-report-release.v1', ?,
                       'current-run-1', ?, 'realized-run-1', ?,
                       'history-1', DATE '2026-01-01', DATE '2026-01-31',
                       'onejournal.pnl.v1', '2026-02-01T00:00:00Z',
                       'draft', NULL, NULL, 0, 0, 0, 0, '{}'
                   )""",
                ["a" * 64, "b" * 64, "c" * 64],
            )

        with self.assertRaisesRegex(
            duckdb.InvalidInputException,
            "requires empty phase1 reporting release tables",
        ):
            apply_schema_migrations(
                blocked_path,
                migrations_dir=MIGRATIONS_DIR,
            )

        with duckdb.connect(str(blocked_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT max(version) FROM schema_migrations").fetchone(),
                ("0024",),
            )
            self.assertEqual(
                con.execute(
                    "SELECT report_release_uid FROM phase1_reporting_releases"
                ).fetchall(),
                [("release-1",)],
            )
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(phase1_reporting_releases)"
                ).fetchall()
            }
            self.assertNotIn("current_owner_acceptance_uid", columns)

    def test_migration_0026_requires_empty_releases(self) -> None:
        apply_schema_migrations(
            self.db_path,
            target_version="0025",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """INSERT INTO phase1_reporting_releases VALUES (
                       'release-1',
                       'onejournal.phase1-report-release.v1', ?,
                       'current-run-1', ?, 'current-acceptance-1',
                       '2026-01-31T22:00:00Z', 'realized-run-1', ?,
                       'realized-acceptance-1', '2026-01-31T23:00:00Z',
                       'history-1', DATE '2026-01-01', DATE '2026-01-31',
                       'onejournal.pnl.v1', '2026-02-01T00:00:00Z',
                       'draft', NULL, NULL, 0, 0, 0, 0, '{}'
                   )""",
                ["a" * 64, "b" * 64, "c" * 64],
            )

        with self.assertRaisesRegex(
            duckdb.InvalidInputException,
            "requires empty phase1 reporting release tables",
        ):
            apply_schema_migrations(
                self.db_path,
                migrations_dir=MIGRATIONS_DIR,
            )

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT max(version) FROM schema_migrations").fetchone(),
                ("0025",),
            )
            realized_type = {
                row[1]: row[2]
                for row in con.execute(
                    "PRAGMA table_info(phase1_reporting_release_realized_items)"
                ).fetchall()
            }["realized_pnl"]
            self.assertEqual(realized_type, "DECIMAL(38,13)")

    def test_init_schema_is_idempotent(self) -> None:
        init_schema(self.db_path)
        init_schema(self.db_path)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 26)

    def test_migration_0005_backfills_existing_reviews_from_version_0002(self) -> None:
        apply_schema_migrations(
            self.db_path,
            target_version="0002",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                INSERT INTO trade_episodes (
                    episode_uid, source_broker, source_account_id, primary_symbol,
                    asset_class, strategy_type, strategy_label, opened_at, status,
                    fill_count, leg_count, updated_at
                ) VALUES (
                    'episode-1', 'manual_csv', 'account-1', 'AAPL', 'stock',
                    'stock_long', 'Stock Long', TIMESTAMP '2026-01-01 10:00:00',
                    'open', 1, 1, TIMESTAMP '2026-01-01 10:00:00'
                )
                """
            )
            con.execute(
                """
                INSERT INTO manual_reviews (
                    episode_uid, review_status, setup_quality, entry_reason, notes, updated_at
                ) VALUES (
                    'episode-1', 'reviewed', 'good', 'planned', 'kept risk small',
                    TIMESTAMP '2026-01-02 12:30:00'
                )
                """
            )

        resulting_version = apply_schema_migrations(
            self.db_path,
            migrations_dir=MIGRATIONS_DIR,
        )
        self.assertEqual(resulting_version, 26)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT episode_uid, review_status, setup_quality, entry_reason,
                       notes, source, created_at
                FROM journal_reviews
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    (
                        "episode-1",
                        "reviewed",
                        "good",
                        "planned",
                        "kept risk small",
                        "legacy_backfill",
                        datetime(2026, 1, 2, 12, 30),
                    )
                ],
            )

    def test_checksum_mismatch_blocks_reapply(self) -> None:
        with tempfile.TemporaryDirectory() as local_migration_dir:
            local_dir = Path(local_migration_dir)
            shutil.copytree(MIGRATIONS_DIR, local_dir / "migrations")
            local_migrations = local_dir / "migrations"
            apply_schema_migrations(self.db_path, migrations_dir=local_migrations)

            migration_file = local_migrations / "0001_establish_schema_version.sql"
            migration_file.write_text(migration_file.read_text() + "\n-- drift marker\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                apply_schema_migrations(self.db_path, migrations_dir=local_migrations)

    def test_partial_schema_is_rejected(self) -> None:
        con = duckdb.connect(str(self.db_path))
        try:
            con.execute(BASELINE_TABLE_DEFINITIONS["import_runs"])
        finally:
            con.close()

        with self.assertRaisesRegex(RuntimeError, "partially-created schema"):
            apply_schema_migrations(self.db_path, migrations_dir=MIGRATIONS_DIR)


if __name__ == "__main__":
    unittest.main()
