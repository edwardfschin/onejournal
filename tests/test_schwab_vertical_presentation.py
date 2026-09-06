from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.schwab_vertical_presentation import (
    VERTICAL_PRESENTATION_CONTRACT_VERSION,
    load_schwab_vertical_presentation_groups,
    presentation_group_to_dict,
)


class SchwabVerticalPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "vertical.duckdb"
        with duckdb.connect(str(self.db_path)) as con:
            con.execute("CREATE TABLE normalized_fills (fill_uid VARCHAR, source_order_id VARCHAR, open_close VARCHAR)")
            con.execute("CREATE TABLE phase1_journal_materialized_episode_fills (fill_uid VARCHAR, episode_uid VARCHAR)")
            con.execute("""
                CREATE TABLE phase1_journal_projected_instruments (
                    episode_uid VARCHAR, instrument_uid VARCHAR, underlying_symbol VARCHAR,
                    option_type VARCHAR, expiry DATE, strike DECIMAL(20,6),
                    opening_direction VARCHAR, currency VARCHAR, asset_class VARCHAR
                )
            """)
            con.execute("""
                CREATE TABLE phase1_journal_projected_executions (
                    fill_uid VARCHAR, episode_uid VARCHAR, instrument_uid VARCHAR,
                    quantity DECIMAL(20,6), fill_price DECIMAL(20,6),
                    schwab_net_cash_movement DECIMAL(20,6), commission DECIMAL(20,6),
                    fees DECIMAL(20,6), execution_index INTEGER
                )
            """)
            con.execute("CREATE TABLE phase1_schwab_evidence_v2_import_families (assembly_uid VARCHAR, family VARCHAR, records_json VARCHAR)")
            con.execute("""
                CREATE TABLE phase1_journal_lifecycle_reconciliation_runs (
                    reconciliation_uid VARCHAR, assembly_uid VARCHAR, asof_date DATE,
                    reconciled_at TIMESTAMP
                )
            """)
            con.execute("CREATE TABLE phase1_journal_episode_lifecycle_states (reconciliation_uid VARCHAR, episode_uid VARCHAR, reconciled_status VARCHAR)")
            con.execute("CREATE TABLE trade_episodes (episode_uid VARCHAR, opened_at TIMESTAMP)")
            con.execute(
                "INSERT INTO phase1_journal_lifecycle_reconciliation_runs VALUES ('recon-1', 'assembly-1', DATE '2026-09-04', TIMESTAMP '2026-09-06 12:00:00')"
            )
            con.execute(
                "INSERT INTO phase1_schwab_evidence_v2_import_families VALUES ('assembly-1', 'orders', ?)",
                [json.dumps([{
                    "source_order_id": "private-order-must-not-leak",
                    "status": "FILLED",
                    "complex_strategy_type": "VERTICAL",
                    "leg_count": 2,
                }])],
            )
            for episode_uid, instrument_uid, strike, direction, fill_uid, price, cash, fees in (
                ("episode-long", "instrument-long", 505, "LONG", "fill-long", 12, -1200.50, 0.50),
                ("episode-short", "instrument-short", 555, "SHORT", "fill-short", 5, 500.25, 0.25),
            ):
                con.execute(
                    "INSERT INTO trade_episodes VALUES (?, TIMESTAMP '2026-08-13 13:36:00')",
                    [episode_uid],
                )
                con.execute(
                    "INSERT INTO phase1_journal_episode_lifecycle_states VALUES ('recon-1', ?, 'open')",
                    [episode_uid],
                )
                con.execute(
                    "INSERT INTO normalized_fills VALUES (?, 'private-order-must-not-leak', 'OPEN')",
                    [fill_uid],
                )
                con.execute(
                    "INSERT INTO phase1_journal_materialized_episode_fills VALUES (?, ?)",
                    [fill_uid, episode_uid],
                )
                con.execute(
                    """
                    INSERT INTO phase1_journal_projected_instruments
                    VALUES (?, ?, 'MSFT', 'CALL', DATE '2027-01-15', ?, ?, 'USD', 'option')
                    """,
                    [episode_uid, instrument_uid, strike, direction],
                )
                con.execute(
                    """
                    INSERT INTO phase1_journal_projected_executions
                    VALUES (?, ?, ?, 1, ?, ?, 0, ?, 1)
                    """,
                    [fill_uid, episode_uid, instrument_uid, price, cash, fees],
                )

    def test_exact_filled_vertical_becomes_one_privacy_safe_presentation_group(self) -> None:
        groups = load_schwab_vertical_presentation_groups(self.db_path)

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group.contract_version, VERTICAL_PRESENTATION_CONTRACT_VERSION)
        self.assertEqual(group.strategy_label, "Call Debit Vertical")
        self.assertEqual(group.primary_symbol, "MSFT")
        self.assertEqual(group.expiry, date(2027, 1, 15))
        self.assertEqual(group.quantity, "1")
        self.assertEqual(group.net_opening_cash_movement, "-700.25")
        self.assertEqual(group.fees, "0.75")
        self.assertEqual(group.episode_status, "open")
        self.assertEqual([member.role for member in group.members], ["LONG", "SHORT"])
        self.assertEqual([member.strike for member in group.members], ["505", "555"])
        serialized = json.dumps(presentation_group_to_dict(group), default=str)
        self.assertNotIn("private-order-must-not-leak", serialized)
        self.assertNotIn("source_order_id", serialized)

    def test_non_filled_order_never_creates_a_group(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            records = [{
                "source_order_id": "private-order-must-not-leak",
                "status": "CANCELED",
                "complex_strategy_type": "VERTICAL",
                "leg_count": 2,
            }]
            con.execute(
                "UPDATE phase1_schwab_evidence_v2_import_families SET records_json = ?",
                [json.dumps(records)],
            )

        self.assertEqual(load_schwab_vertical_presentation_groups(self.db_path), ())

    def test_repeated_opening_order_scales_one_existing_pair(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            records = [
                {
                    "source_order_id": source_order_id,
                    "status": "FILLED",
                    "complex_strategy_type": "VERTICAL",
                    "leg_count": 2,
                }
                for source_order_id in (
                    "private-order-must-not-leak",
                    "private-scale-order-must-not-leak",
                )
            ]
            con.execute(
                "UPDATE phase1_schwab_evidence_v2_import_families SET records_json = ?",
                [json.dumps(records)],
            )
            for episode_uid, instrument_uid, fill_uid, price, cash, fees in (
                ("episode-long", "instrument-long", "fill-long-scale", 11, -2201, 1),
                ("episode-short", "instrument-short", "fill-short-scale", 4, 800.50, 0.50),
            ):
                con.execute(
                    "INSERT INTO normalized_fills VALUES (?, 'private-scale-order-must-not-leak', 'OPEN')",
                    [fill_uid],
                )
                con.execute(
                    "INSERT INTO phase1_journal_materialized_episode_fills VALUES (?, ?)",
                    [fill_uid, episode_uid],
                )
                con.execute(
                    """
                    INSERT INTO phase1_journal_projected_executions
                    VALUES (?, ?, ?, 2, ?, ?, 0, ?, 2)
                    """,
                    [fill_uid, episode_uid, instrument_uid, price, cash, fees],
                )

        groups = load_schwab_vertical_presentation_groups(self.db_path)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].quantity, "3")
        self.assertEqual(groups[0].net_opening_cash_movement, "-2100.75")
        serialized = json.dumps(presentation_group_to_dict(groups[0]), default=str)
        self.assertNotIn("private-scale-order-must-not-leak", serialized)


if __name__ == "__main__":
    unittest.main()
