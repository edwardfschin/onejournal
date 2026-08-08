from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb

from onejournal.journal.migrations import (
    BASELINE_TABLE_DEFINITIONS,
    apply_schema_migrations,
)
from scripts.journal.init_journal_db import init_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


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

            rows = con.execute("SELECT version, status FROM schema_migrations ORDER BY version").fetchall()
            self.assertEqual(rows[0][0], "0001")
            self.assertEqual(rows[0][1], "applied")
            self.assertEqual(rows[1][0], "0002")
            self.assertEqual(rows[1][1], "applied")
            self.assertEqual(rows[2][0], "0003")
            self.assertEqual(rows[2][1], "applied")

    def test_init_schema_is_idempotent(self) -> None:
        init_schema(self.db_path)
        init_schema(self.db_path)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 3)

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
