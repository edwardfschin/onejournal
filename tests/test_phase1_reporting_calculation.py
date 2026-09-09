from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.phase1_reporting_calculation import (
    Phase1RealizedCalculationError,
    RealizedResultAuthorization,
    authorize_realized_result,
    calculate_bounded_realized_result,
    reporting_items,
    reporting_omissions,
    validate_realized_result,
)


class Phase1ReportingCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "reporting-calculation.duckdb"
        with duckdb.connect(str(self.db_path)) as con:
            self._create_schema(con)
            self._insert_history(con)

    @staticmethod
    def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            """
            CREATE TABLE normalized_fills (
                fill_uid VARCHAR, source_broker VARCHAR, source_account_id VARCHAR,
                source_fill_id VARCHAR, source_order_id VARCHAR,
                episode_group_id VARCHAR, asof_date DATE, filled_at_utc VARCHAR,
                asset_class VARCHAR, symbol VARCHAR, side VARCHAR,
                quantity DECIMAL(38,10), fill_price DECIMAL(38,10),
                commission DECIMAL(38,10), fees DECIMAL(38,10), currency VARCHAR,
                fetched_at_utc VARCHAR, raw_path VARCHAR, option_symbol VARCHAR,
                underlying_symbol VARCHAR, option_type VARCHAR, expiry DATE,
                strike DECIMAL(38,10), multiplier DECIMAL(38,10),
                open_close VARCHAR, execution_venue VARCHAR, liquidity_flag VARCHAR
            );
            CREATE TABLE normalized_lifecycle_events (
                event_uid VARCHAR, source_broker VARCHAR, source_account_id VARCHAR,
                event_type VARCHAR, event_at_utc VARCHAR, asof_date DATE
            );
            CREATE TABLE normalized_lifecycle_event_legs (
                event_leg_uid VARCHAR, event_uid VARCHAR
            );
            CREATE TABLE approved_option_lifecycle_events (
                event_uid VARCHAR, event_type VARCHAR, source_broker VARCHAR,
                source_account_id VARCHAR, currency VARCHAR,
                effective_at_utc VARCHAR, option_instrument_key VARCHAR,
                predecessor_direction VARCHAR, contracts DECIMAL(38,10),
                event_commission DECIMAL(38,10), event_fees DECIMAL(38,10),
                evidence_status VARCHAR, successor_action VARCHAR,
                successor_position_effect VARCHAR, successor_symbol VARCHAR,
                successor_quantity DECIMAL(38,10),
                strike_cash_amount DECIMAL(38,10)
            );
            CREATE TABLE approved_option_lifecycle_predecessors (
                event_uid VARCHAR, predecessor_index INTEGER, open_fill_uid VARCHAR
            );
            CREATE TABLE approved_option_lifecycle_source_legs (
                event_uid VARCHAR, event_leg_uid VARCHAR
            );
            CREATE TABLE phase1_journal_history_revisions (
                revision_uid VARCHAR, result_fingerprint VARCHAR,
                source_broker VARCHAR, source_account_id VARCHAR,
                history_window_start DATE, history_window_end DATE, asof_date DATE
                , fill_count INTEGER, episode_count INTEGER,
                execution_count INTEGER,
                lifecycle_resolved_scope_count INTEGER,
                review_required_scope_count INTEGER,
                closed_count INTEGER, open_count INTEGER,
                review_required_count INTEGER, lifecycle_final_status VARCHAR
            );
            CREATE TABLE phase1_journal_current_revision_ids (revision_uid VARCHAR);
            CREATE TABLE phase1_journal_history_revision_episodes (
                revision_uid VARCHAR, episode_uid VARCHAR, source_broker VARCHAR,
                source_account_id VARCHAR, scope_uid VARCHAR,
                primary_symbol VARCHAR,
                lifecycle_quality VARCHAR,
                materialization_lifecycle_quality VARCHAR,
                reconciled_status VARCHAR, reason_code VARCHAR,
                materialization_reason_code VARCHAR,
                position_reconciliation_status VARCHAR
            );
            CREATE TABLE phase1_journal_history_revision_episode_fills (
                revision_uid VARCHAR, episode_uid VARCHAR,
                leg_index INTEGER, fill_uid VARCHAR
            );
            CREATE TABLE phase1_journal_history_revision_executions (
                revision_uid VARCHAR, episode_uid VARCHAR, fill_uid VARCHAR,
                net_amount_reconciled BOOLEAN
            );
            """
        )

    @staticmethod
    def _fill(
        uid: str,
        *,
        episode_uid: str,
        side: str,
        open_close: str,
        price: str,
        filled_at: str,
    ) -> tuple[object, ...]:
        return (
            uid,
            "schwab",
            "private-account",
            f"source-{uid}",
            f"order-{uid}",
            episode_uid,
            date(2026, 1, 31),
            filled_at,
            "equity",
            "ABC",
            side,
            Decimal("10"),
            Decimal(price),
            Decimal("0"),
            Decimal("0"),
            "USD",
            "2026-02-01T00:00:00Z",
            None,
            None,
            None,
            None,
            None,
            None,
            Decimal("1"),
            open_close,
            None,
            None,
        )

    def _insert_history(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            "INSERT INTO phase1_journal_history_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "revision-1",
                "a" * 64,
                "schwab",
                "private-account",
                date(2026, 1, 1),
                date(2026, 1, 31),
                date(2026, 1, 31),
                3,
                2,
                3,
                1,
                1,
                1,
                0,
                1,
                "review_required",
            ],
        )
        con.execute("INSERT INTO phase1_journal_current_revision_ids VALUES ('revision-1')")
        con.executemany(
            "INSERT INTO phase1_journal_history_revision_episodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "revision-1",
                    "resolved-episode",
                    "schwab",
                    "private-account",
                    "resolved-scope",
                    "ABC",
                    "resolved",
                    "resolved",
                    "closed",
                    None,
                    None,
                    "not_applicable",
                ),
                (
                    "revision-1",
                    "unresolved-episode",
                    "schwab",
                    "private-account",
                    "unresolved-scope",
                    "XYZ",
                    "absent_current",
                    "review_required",
                    "review_required",
                    "history_extension_required",
                    None,
                    "review_required",
                ),
            ],
        )
        fills = [
            self._fill(
                "open-1",
                episode_uid="resolved-episode",
                side="BUY",
                open_close="OPEN",
                price="10",
                filled_at="2026-01-02T15:00:00Z",
            ),
            self._fill(
                "close-1",
                episode_uid="resolved-episode",
                side="SELL",
                open_close="CLOSE",
                price="12",
                filled_at="2026-01-03T15:00:00Z",
            ),
            self._fill(
                "unmatched-1",
                episode_uid="unresolved-episode",
                side="SELL",
                open_close="CLOSE",
                price="9",
                filled_at="2026-01-04T15:00:00Z",
            ),
        ]
        placeholders = ", ".join("?" for _ in range(27))
        con.executemany(f"INSERT INTO normalized_fills VALUES ({placeholders})", fills)
        con.executemany(
            "INSERT INTO phase1_journal_history_revision_episode_fills VALUES (?, ?, ?, ?)",
            [
                ("revision-1", "resolved-episode", 1, "open-1"),
                ("revision-1", "resolved-episode", 2, "close-1"),
                ("revision-1", "unresolved-episode", 1, "unmatched-1"),
            ],
        )
        con.executemany(
            "INSERT INTO phase1_journal_history_revision_executions VALUES (?, ?, ?, TRUE)",
            [
                ("revision-1", "resolved-episode", "open-1"),
                ("revision-1", "resolved-episode", "close-1"),
                ("revision-1", "unresolved-episode", "unmatched-1"),
            ],
        )

    def test_calculation_is_read_only_deterministic_and_explicitly_incomplete(self) -> None:
        before = sha256(self.db_path.read_bytes()).hexdigest()
        first = calculate_bounded_realized_result(
            self.db_path, calculated_at=datetime(2026, 2, 1, tzinfo=UTC)
        )
        second = calculate_bounded_realized_result(
            self.db_path, calculated_at=datetime(2026, 2, 2, tzinfo=UTC)
        )
        after = sha256(self.db_path.read_bytes()).hexdigest()

        self.assertEqual(before, after)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)
        self.assertEqual(first.calculation_run_id, second.calculation_run_id)
        self.assertEqual(first.quality, "incomplete")
        self.assertEqual(len(first.items), 1)
        self.assertEqual(first.items[0].realized_pnl, Decimal("20"))
        self.assertEqual(len(first.omissions), 1)
        self.assertEqual(first.reason_counts, {"opening_history_missing": 1})
        self.assertEqual(len(reporting_items(first)), 1)
        self.assertEqual(len(reporting_omissions(first)), 1)

    def test_owner_authorization_is_exact_and_tamper_evident(self) -> None:
        result = calculate_bounded_realized_result(self.db_path)
        authorization = RealizedResultAuthorization(
            calculation_run_id=result.calculation_run_id,
            result_fingerprint=result.result_fingerprint,
            history_revision_uids=tuple(x.revision_uid for x in result.authorities),
            owner_acceptance_uid="owner-acceptance-1",
            accepted_at_utc=datetime(2026, 2, 1, tzinfo=UTC),
        )
        authorize_realized_result(result, authorization)

        with self.assertRaisesRegex(
            Phase1RealizedCalculationError, "authorization does not match"
        ):
            authorize_realized_result(
                result,
                replace(authorization, result_fingerprint="b" * 64),
            )
        with self.assertRaisesRegex(
            Phase1RealizedCalculationError, "fingerprint mismatch"
        ):
            validate_realized_result(
                replace(
                    result,
                    items=(replace(result.items[0], realized_pnl=Decimal("21")),),
                )
            )

    def test_unmatched_close_in_resolved_scope_fails_closed(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                UPDATE phase1_journal_history_revision_episodes
                SET lifecycle_quality='resolved',
                    materialization_lifecycle_quality='resolved',
                    reconciled_status='closed',
                    reason_code=NULL,
                    position_reconciliation_status='not_applicable'
                WHERE episode_uid='unresolved-episode'
                """
            )
            con.execute(
                """
                UPDATE phase1_journal_history_revisions
                SET lifecycle_resolved_scope_count=2,
                    review_required_scope_count=0,
                    closed_count=2,
                    review_required_count=0,
                    lifecycle_final_status='reconciled'
                WHERE revision_uid='revision-1'
                """
            )
        with self.assertRaisesRegex(
            Phase1RealizedCalculationError,
            "unmatched close exists in a resolved history scope",
        ):
            calculate_bounded_realized_result(self.db_path)

    def test_lifecycle_review_has_a_distinct_omission_reason(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                UPDATE phase1_journal_history_revision_episodes
                SET reason_code='broker_terminal_event_review_required',
                    position_reconciliation_status='terminal_reconciled'
                WHERE episode_uid='unresolved-episode'
                """
            )

        result = calculate_bounded_realized_result(self.db_path)

        self.assertEqual(result.reason_counts, {"lifecycle_review_required": 1})

    def test_stale_active_revision_is_rejected(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            placeholders = ", ".join("?" for _ in range(27))
            con.execute(
                f"INSERT INTO normalized_fills VALUES ({placeholders})",
                self._fill(
                    "newer-fill",
                    episode_uid="unrepresented-episode",
                    side="BUY",
                    open_close="OPEN",
                    price="8",
                    filled_at="2026-01-05T15:00:00Z",
                ),
            )

        with self.assertRaisesRegex(
            Phase1RealizedCalculationError,
            "active history revision is stale against normalized fill evidence",
        ):
            calculate_bounded_realized_result(self.db_path)

    def test_unreconciled_execution_is_rejected(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                UPDATE phase1_journal_history_revision_executions
                SET net_amount_reconciled=FALSE
                WHERE rowid=(
                    SELECT min(rowid)
                    FROM phase1_journal_history_revision_executions
                )
                """
            )

        with self.assertRaisesRegex(
            Phase1RealizedCalculationError,
            "active history contains unreconciled execution economics",
        ):
            calculate_bounded_realized_result(self.db_path)


if __name__ == "__main__":
    unittest.main()
