#!/usr/bin/env python3
"""Validate OneJournal DuckDB journal storage.

Read-only DB health check.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/journal/onejournal.duckdb")
REQUIRED_TABLES = [
    "import_runs",
    "normalized_fills",
    "normalized_accounts",
    "normalized_orders",
    "normalized_positions",
    "normalized_transactions",
    "normalized_lifecycle_events",
    "normalized_lifecycle_event_legs",
    "approved_option_lifecycle_events",
    "approved_option_lifecycle_predecessors",
    "approved_option_lifecycle_source_legs",
    "pnl_calculation_runs",
    "pnl_group_results",
    "pnl_closed_lot_allocations",
    "pnl_lifecycle_allocations",
    "trade_episodes",
    "trade_episode_legs",
    "manual_reviews",
    "journal_entries",
    "journal_entry_revisions",
    "journal_reviews",
    "journal_strategies",
    "journal_tags",
    "journal_entry_tag_events",
    "journal_attachments",
    "journal_saved_views",
    "journal_goals",
    "journal_goal_checkins",
    "journal_habits",
    "journal_habit_events",
    "journal_review_period_events",
    "phase1_journal_materialization_runs",
    "phase1_journal_materialized_fills",
    "phase1_journal_materialized_episodes",
    "phase1_journal_materialized_episode_fills",
    "phase1_journal_execution_projection_runs",
    "phase1_journal_projected_episodes",
    "phase1_journal_projected_instruments",
    "phase1_journal_projected_executions",
    "phase1_schwab_evidence_v2_import_runs",
    "phase1_schwab_evidence_v2_import_families",
    "phase1_journal_lifecycle_reconciliation_runs",
    "phase1_journal_episode_lifecycle_states",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OneJournal DuckDB journal storage.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"FAIL {message}")


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    print("===== OneJournal DB check =====")
    print(f"DB        : {db_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    if not db_path.exists():
        fail(f"DB not found: {db_path}")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        missing = sorted(set(REQUIRED_TABLES) - tables)
        if missing:
            fail(f"missing required table(s): {missing}")

        counts = {}
        for table in REQUIRED_TABLES:
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {counts[table]}")

        history_revision_tables = {
            "phase1_journal_history_revisions",
            "phase1_journal_history_revision_episodes",
            "phase1_journal_history_revision_episode_fills",
            "phase1_journal_history_revision_instruments",
            "phase1_journal_history_revision_executions",
            "phase1_journal_history_revision_activations",
            "journal_current_trade_episodes",
            "journal_current_projected_executions",
        }
        history_revisions_available = history_revision_tables.issubset(tables)
        invalid_history_revision_counts = 0
        duplicate_current_revision_fills = 0
        invalid_current_revision_selection = 0
        if history_revisions_available:
            for table in sorted(history_revision_tables):
                value = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"{table}: {value}")
            invalid_history_revision_counts = con.execute(
                """
                SELECT COUNT(*) FROM phase1_journal_history_revisions r
                WHERE r.episode_count <> (
                    SELECT COUNT(*) FROM phase1_journal_history_revision_episodes e
                    WHERE e.revision_uid = r.revision_uid
                ) OR r.fill_count <> (
                    SELECT COUNT(*) FROM phase1_journal_history_revision_episode_fills f
                    WHERE f.revision_uid = r.revision_uid
                ) OR r.instrument_count <> (
                    SELECT COUNT(*) FROM phase1_journal_history_revision_instruments i
                    WHERE i.revision_uid = r.revision_uid
                ) OR r.execution_count <> (
                    SELECT COUNT(*) FROM phase1_journal_history_revision_executions x
                    WHERE x.revision_uid = r.revision_uid
                )
                """
            ).fetchone()[0]
            duplicate_current_revision_fills = con.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT fill_uid FROM journal_current_projected_executions
                    GROUP BY fill_uid HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
            invalid_current_revision_selection = con.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT source_broker, source_account_id
                    FROM phase1_journal_current_revision_ids
                    GROUP BY source_broker, source_account_id
                    HAVING COUNT(*) <> 1
                )
                """
            ).fetchone()[0]

        if counts["normalized_fills"] <= 0:
            fail("normalized_fills has no rows")
        phase1_materialized = counts["phase1_journal_materialization_runs"] > 0
        if not phase1_materialized:
            if counts["normalized_accounts"] <= 0:
                fail("normalized_accounts has no rows")
            if counts["normalized_orders"] <= 0:
                fail("normalized_orders has no rows")
            if counts["normalized_positions"] <= 0:
                fail("normalized_positions has no rows")
            if counts["normalized_transactions"] <= 0:
                fail("normalized_transactions has no rows")
        else:
            print(
                "NOTE exact Phase 1 evidence families replace legacy fill-derived "
                "placeholder account/order/position/transaction rows"
            )
        if counts["trade_episodes"] <= 0:
            fail("trade_episodes has no rows")
        if counts["manual_reviews"] <= 0:
            print("NOTE manual_reviews has no rows; OK for broker-only imports before manual review")
        if counts["trade_episode_legs"] < counts["trade_episodes"]:
            fail("trade_episode_legs count is less than trade_episodes count")

        duplicate_fills = con.execute(
            "SELECT COUNT(*) FROM (SELECT fill_uid FROM normalized_fills GROUP BY fill_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_accounts = con.execute(
            "SELECT COUNT(*) FROM (SELECT account_uid FROM normalized_accounts GROUP BY account_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_orders = con.execute(
            "SELECT COUNT(*) FROM (SELECT order_uid FROM normalized_orders GROUP BY order_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_positions = con.execute(
            "SELECT COUNT(*) FROM (SELECT position_uid FROM normalized_positions GROUP BY position_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_transactions = con.execute(
            "SELECT COUNT(*) FROM (SELECT transaction_uid FROM normalized_transactions GROUP BY transaction_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_lifecycle_events = con.execute(
            "SELECT COUNT(*) FROM (SELECT event_uid FROM normalized_lifecycle_events GROUP BY event_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_lifecycle_event_legs = con.execute(
            "SELECT COUNT(*) FROM (SELECT event_leg_uid FROM normalized_lifecycle_event_legs GROUP BY event_leg_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_lifecycle_event_indexes = con.execute(
            "SELECT COUNT(*) FROM (SELECT event_uid, leg_index FROM normalized_lifecycle_event_legs GROUP BY event_uid, leg_index HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        orphaned_lifecycle_event_legs = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_event_legs l
            LEFT JOIN normalized_lifecycle_events e ON e.event_uid = l.event_uid
            WHERE e.event_uid IS NULL
            """
        ).fetchone()[0]
        orphaned_approved_events = con.execute(
            """
            SELECT COUNT(*)
            FROM approved_option_lifecycle_events a
            LEFT JOIN normalized_lifecycle_events e ON e.event_uid = a.event_uid
            WHERE e.event_uid IS NULL
            """
        ).fetchone()[0]
        orphaned_approved_predecessors = con.execute(
            """
            SELECT COUNT(*)
            FROM approved_option_lifecycle_predecessors p
            LEFT JOIN approved_option_lifecycle_events a ON a.event_uid = p.event_uid
            LEFT JOIN normalized_fills f ON f.fill_uid = p.open_fill_uid
            WHERE a.event_uid IS NULL OR f.fill_uid IS NULL
            """
        ).fetchone()[0]
        orphaned_approved_source_legs = con.execute(
            """
            SELECT COUNT(*)
            FROM approved_option_lifecycle_source_legs s
            LEFT JOIN approved_option_lifecycle_events a ON a.event_uid = s.event_uid
            LEFT JOIN normalized_lifecycle_event_legs l
              ON l.event_leg_uid = s.event_leg_uid AND l.event_uid = s.event_uid
            WHERE a.event_uid IS NULL OR l.event_leg_uid IS NULL
            """
        ).fetchone()[0]
        orphaned_pnl_children = con.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM pnl_group_results g
                 LEFT JOIN pnl_calculation_runs r USING (calculation_run_id)
                 WHERE r.calculation_run_id IS NULL)
              + (SELECT COUNT(*) FROM pnl_closed_lot_allocations c
                 LEFT JOIN pnl_calculation_runs r USING (calculation_run_id)
                 WHERE r.calculation_run_id IS NULL)
              + (SELECT COUNT(*) FROM pnl_lifecycle_allocations l
                 LEFT JOIN pnl_calculation_runs r USING (calculation_run_id)
                 WHERE r.calculation_run_id IS NULL)
            """
        ).fetchone()[0]
        pnl_run_count_mismatches = con.execute(
            """
            SELECT COUNT(*)
            FROM pnl_calculation_runs r
            WHERE r.group_count <> (
                    SELECT COUNT(*) FROM pnl_group_results g
                    WHERE g.calculation_run_id = r.calculation_run_id
                  )
               OR r.closed_allocation_count <> (
                    SELECT COUNT(*) FROM pnl_closed_lot_allocations c
                    WHERE c.calculation_run_id = r.calculation_run_id
                  )
               OR r.lifecycle_allocation_count <> (
                    SELECT COUNT(*) FROM pnl_lifecycle_allocations l
                    WHERE l.calculation_run_id = r.calculation_run_id
                  )
            """
        ).fetchone()[0]
        invalid_pnl_lifecycle_links = con.execute(
            """
            SELECT COUNT(*)
            FROM pnl_lifecycle_allocations l
            LEFT JOIN approved_option_lifecycle_events a ON a.event_uid = l.event_uid
            LEFT JOIN normalized_fills f ON f.fill_uid = l.predecessor_open_fill_uid
            WHERE a.event_uid IS NULL OR f.fill_uid IS NULL
            """
        ).fetchone()[0]
        duplicate_episodes = con.execute(
            "SELECT COUNT(*) FROM (SELECT episode_uid FROM trade_episodes GROUP BY episode_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_reviews = con.execute(
            "SELECT COUNT(*) FROM (SELECT episode_uid FROM manual_reviews GROUP BY episode_uid HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        duplicate_entry_revisions = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT entry_uid, revision_no FROM journal_entry_revisions
                GROUP BY entry_uid, revision_no HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        competing_review_heads = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT r.episode_uid
                FROM journal_reviews r
                WHERE NOT EXISTS (
                    SELECT 1 FROM journal_reviews child
                    WHERE child.supersedes_review_uid = r.review_uid
                )
                GROUP BY r.episode_uid HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        orphaned_entry_links = con.execute(
            """
            WITH current_revisions AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY entry_uid ORDER BY revision_no DESC
                ) AS rn
                FROM journal_entry_revisions
            )
            SELECT COUNT(*)
            FROM current_revisions r
            WHERE r.rn = 1 AND r.episode_uid IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM trade_episodes e WHERE e.episode_uid = r.episode_uid
              )
            """
        ).fetchone()[0]
        orphaned_review_links = con.execute(
            """
            SELECT COUNT(*)
            FROM journal_reviews r
            WHERE NOT EXISTS (
                SELECT 1 FROM trade_episodes e WHERE e.episode_uid = r.episode_uid
            )
            """
        ).fetchone()[0]
        cross_episode_review_links = con.execute(
            """
            SELECT COUNT(*)
            FROM journal_reviews child
            JOIN journal_reviews parent
              ON parent.review_uid = child.supersedes_review_uid
            WHERE child.episode_uid <> parent.episode_uid
            """
        ).fetchone()[0]
        missing_review_heads = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT episode_uid
                FROM journal_reviews
                GROUP BY episode_uid
                HAVING SUM(CASE WHEN review_uid NOT IN (
                    SELECT supersedes_review_uid
                    FROM journal_reviews
                    WHERE supersedes_review_uid IS NOT NULL
                ) THEN 1 ELSE 0 END) = 0
            )
            """
        ).fetchone()[0]
        phase1_run_count_mismatches = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_materialization_runs r
            WHERE r.fill_count <> (
                    SELECT COUNT(*) FROM phase1_journal_materialized_fills f
                    WHERE f.materialization_uid = r.materialization_uid
                  )
               OR r.episode_count <> (
                    SELECT COUNT(*) FROM phase1_journal_materialized_episodes e
                    WHERE e.materialization_uid = r.materialization_uid
                  )
               OR r.fill_count <> (
                    SELECT COUNT(*) FROM phase1_journal_materialized_episode_fills l
                    WHERE l.materialization_uid = r.materialization_uid
                  )
            """
        ).fetchone()[0]
        orphaned_phase1_materialization_links = con.execute(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM phase1_journal_materialized_fills m
                 LEFT JOIN normalized_fills f ON f.fill_uid = m.fill_uid
                 WHERE f.fill_uid IS NULL)
              + (SELECT COUNT(*)
                 FROM phase1_journal_materialized_episodes m
                 LEFT JOIN trade_episodes e ON e.episode_uid = m.episode_uid
                 WHERE e.episode_uid IS NULL)
              + (SELECT COUNT(*)
                 FROM phase1_journal_materialized_episode_fills l
                 LEFT JOIN trade_episode_legs e
                   ON e.episode_uid = l.episode_uid AND e.leg_index = l.leg_index
                 WHERE e.episode_uid IS NULL)
            """
        ).fetchone()[0]
        unsafe_review_required_aggregates = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_materialized_episodes m
            JOIN trade_episodes e ON e.episode_uid = m.episode_uid
            WHERE m.lifecycle_quality = 'review_required'
              AND (e.net_quantity IS NOT NULL OR e.gross_cashflow IS NOT NULL
                   OR e.commission IS NOT NULL OR e.fees IS NOT NULL)
            """
        ).fetchone()[0]
        phase1_projection_run_count_mismatches = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_execution_projection_runs r
            WHERE r.episode_count <> (
                    SELECT COUNT(*) FROM phase1_journal_projected_episodes e
                    WHERE e.projection_uid = r.projection_uid
                  )
               OR r.instrument_count <> (
                    SELECT COUNT(*) FROM phase1_journal_projected_instruments i
                    WHERE i.projection_uid = r.projection_uid
                  )
               OR r.execution_count <> (
                    SELECT COUNT(*) FROM phase1_journal_projected_executions x
                    WHERE x.projection_uid = r.projection_uid
                  )
               OR r.execution_count <> r.schwab_net_amount_match_count
               OR r.schwab_net_amount_mismatch_count <> 0
            """
        ).fetchone()[0]
        orphaned_phase1_projection_links = con.execute(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM phase1_journal_projected_episodes p
                 LEFT JOIN phase1_journal_materialized_episodes m
                   ON m.episode_uid = p.episode_uid
                 WHERE m.episode_uid IS NULL)
              + (SELECT COUNT(*)
                 FROM phase1_journal_projected_instruments i
                 LEFT JOIN phase1_journal_projected_episodes p
                   ON p.projection_uid = i.projection_uid
                  AND p.episode_uid = i.episode_uid
                 WHERE p.episode_uid IS NULL)
              + (SELECT COUNT(*)
                 FROM phase1_journal_projected_executions x
                 LEFT JOIN normalized_fills f ON f.fill_uid = x.fill_uid
                 WHERE f.fill_uid IS NULL)
              + (SELECT COUNT(*)
                 FROM phase1_journal_projected_executions x
                 LEFT JOIN phase1_journal_projected_instruments i
                   ON i.projection_uid = x.projection_uid
                  AND i.episode_uid = x.episode_uid
                  AND i.instrument_uid = x.instrument_uid
                 WHERE i.instrument_uid IS NULL)
            """
        ).fetchone()[0]
        unprojected_phase1_episodes = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_materialized_episodes m
            LEFT JOIN phase1_journal_projected_episodes p
              ON p.episode_uid = m.episode_uid
            WHERE p.episode_uid IS NULL
            """
        ).fetchone()[0]
        unreconciled_projected_executions = con.execute(
            """
            SELECT COUNT(*) FROM phase1_journal_projected_executions
            WHERE NOT net_amount_reconciled
               OR schwab_net_cash_movement <> calculated_net_cash_movement
            """
        ).fetchone()[0]
        unsafe_single_instrument_strategies = con.execute(
            """
            SELECT COUNT(*) FROM phase1_journal_projected_episodes
            WHERE instrument_count = 1
              AND strategy_type IN (
                'put_credit_vertical', 'put_debit_vertical',
                'call_credit_vertical', 'call_debit_vertical',
                'multi_leg_option', 'multi_instrument_unclassified'
              )
            """
        ).fetchone()[0]
        phase1_v2_family_count_mismatches = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_schwab_evidence_v2_import_runs r
            WHERE 10 <> (
                SELECT COUNT(*)
                FROM phase1_schwab_evidence_v2_import_families f
                WHERE f.assembly_uid = r.assembly_uid
            )
            """
        ).fetchone()[0]
        phase1_lifecycle_run_count_mismatches = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_lifecycle_reconciliation_runs r
            WHERE r.episode_count <> (
                    SELECT COUNT(*)
                    FROM phase1_journal_episode_lifecycle_states s
                    WHERE s.reconciliation_uid = r.reconciliation_uid
                  )
               OR r.episode_count <>
                    r.closed_count + r.open_count + r.review_required_count
               OR r.matched_terminal_event_leg_count > r.terminal_event_leg_count
               OR (
                    r.final_status = 'reconciled'
                    AND EXISTS (
                        SELECT 1
                        FROM phase1_journal_episode_lifecycle_states s
                        WHERE s.reconciliation_uid = r.reconciliation_uid
                          AND (s.reconciled_status = 'review_required'
                               OR s.lifecycle_quality = 'review_required')
                    )
                  )
            """
        ).fetchone()[0]
        orphaned_phase1_lifecycle_links = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_episode_lifecycle_states s
            LEFT JOIN phase1_journal_lifecycle_reconciliation_runs r
              ON r.reconciliation_uid = s.reconciliation_uid
            LEFT JOIN trade_episodes e ON e.episode_uid = s.episode_uid
            WHERE r.reconciliation_uid IS NULL OR e.episode_uid IS NULL
            """
        ).fetchone()[0]
        unreconciled_phase1_episodes = con.execute(
            """
            SELECT COUNT(*)
            FROM phase1_journal_materialized_episodes m
            LEFT JOIN phase1_journal_episode_lifecycle_states s
              ON s.episode_uid = m.episode_uid
            WHERE s.episode_uid IS NULL
            """
        ).fetchone()[0]

        print(f"duplicate_fill_uid: {duplicate_fills}")
        print(f"duplicate_account_uid: {duplicate_accounts}")
        print(f"duplicate_order_uid: {duplicate_orders}")
        print(f"duplicate_position_uid: {duplicate_positions}")
        print(f"duplicate_transaction_uid: {duplicate_transactions}")
        print(f"duplicate_lifecycle_event_uid: {duplicate_lifecycle_events}")
        print(f"duplicate_lifecycle_event_leg_uid: {duplicate_lifecycle_event_legs}")
        print(f"duplicate_lifecycle_event_leg_index: {duplicate_lifecycle_event_indexes}")
        print(f"orphaned_lifecycle_event_legs: {orphaned_lifecycle_event_legs}")
        print(f"orphaned_approved_lifecycle_events: {orphaned_approved_events}")
        print(f"orphaned_approved_predecessors: {orphaned_approved_predecessors}")
        print(f"orphaned_approved_source_legs: {orphaned_approved_source_legs}")
        print(f"orphaned_pnl_children: {orphaned_pnl_children}")
        print(f"pnl_run_count_mismatches: {pnl_run_count_mismatches}")
        print(f"invalid_pnl_lifecycle_links: {invalid_pnl_lifecycle_links}")
        print(f"duplicate_episode_uid: {duplicate_episodes}")
        print(f"duplicate_review_episode_uid: {duplicate_reviews}")
        print(f"duplicate_journal_entry_revision: {duplicate_entry_revisions}")
        print(f"competing_journal_review_heads: {competing_review_heads}")
        print(f"orphaned_journal_entry_links: {orphaned_entry_links}")
        print(f"orphaned_journal_review_links: {orphaned_review_links}")
        print(f"cross_episode_review_supersession: {cross_episode_review_links}")
        print(f"missing_journal_review_heads: {missing_review_heads}")
        print(f"phase1_run_count_mismatches: {phase1_run_count_mismatches}")
        print(f"orphaned_phase1_materialization_links: {orphaned_phase1_materialization_links}")
        print(f"unsafe_review_required_aggregates: {unsafe_review_required_aggregates}")
        print(f"phase1_projection_run_count_mismatches: {phase1_projection_run_count_mismatches}")
        print(f"orphaned_phase1_projection_links: {orphaned_phase1_projection_links}")
        print(f"unprojected_phase1_episodes: {unprojected_phase1_episodes}")
        print(f"unreconciled_projected_executions: {unreconciled_projected_executions}")
        print(f"unsafe_single_instrument_strategies: {unsafe_single_instrument_strategies}")
        print(f"phase1_v2_family_count_mismatches: {phase1_v2_family_count_mismatches}")
        print(f"phase1_lifecycle_run_count_mismatches: {phase1_lifecycle_run_count_mismatches}")
        print(f"orphaned_phase1_lifecycle_links: {orphaned_phase1_lifecycle_links}")
        print(f"unreconciled_phase1_episodes: {unreconciled_phase1_episodes}")

        if duplicate_fills:
            fail("duplicate fill_uid found")
        if duplicate_accounts:
            fail("duplicate account_uid found")
        if duplicate_orders:
            fail("duplicate order_uid found")
        if duplicate_positions:
            fail("duplicate position_uid found")
        if duplicate_transactions:
            fail("duplicate transaction_uid found")
        if duplicate_lifecycle_events:
            fail("duplicate lifecycle event_uid found")
        if duplicate_lifecycle_event_legs:
            fail("duplicate lifecycle event_leg_uid found")
        if duplicate_lifecycle_event_indexes:
            fail("duplicate lifecycle event_uid/leg_index found")
        if orphaned_lifecycle_event_legs:
            fail("orphaned lifecycle event legs found")
        if orphaned_approved_events:
            fail("approved lifecycle events without normalized evidence found")
        if orphaned_approved_predecessors:
            fail("approved lifecycle predecessors without event/fill evidence found")
        if orphaned_approved_source_legs:
            fail("approved lifecycle source legs without matching evidence found")
        if orphaned_pnl_children:
            fail("P&L result rows without calculation runs found")
        if pnl_run_count_mismatches:
            fail("P&L calculation run counts do not match persisted result rows")
        if invalid_pnl_lifecycle_links:
            fail("P&L lifecycle allocations have invalid approved-event/fill links")
        if duplicate_episodes:
            fail("duplicate episode_uid found")
        if duplicate_reviews:
            fail("duplicate manual review episode_uid found")
        if duplicate_entry_revisions:
            fail("duplicate journal entry revision found")
        if competing_review_heads:
            fail("multiple current journal review heads found")
        if orphaned_entry_links:
            fail("orphaned journal entry episode links found")
        if orphaned_review_links:
            fail("orphaned journal review episode links found")
        if cross_episode_review_links:
            fail("cross-episode journal review supersession found")
        if missing_review_heads:
            fail("journal review chain without a current head found")
        if phase1_run_count_mismatches:
            fail("Phase 1 materialization run counts do not match lineage rows")
        if orphaned_phase1_materialization_links:
            fail("orphaned Phase 1 materialization lineage found")
        if unsafe_review_required_aggregates:
            fail("review-required lifecycle has financial aggregates")
        if phase1_materialized and not counts["phase1_journal_execution_projection_runs"]:
            fail("Phase 1 materialization lacks an execution-first projection")
        if phase1_projection_run_count_mismatches:
            fail("Phase 1 execution projection counts do not match projected rows")
        if orphaned_phase1_projection_links:
            fail("orphaned Phase 1 execution projection lineage found")
        if unprojected_phase1_episodes:
            fail("Phase 1 materialized episodes lack corrected projections")
        if unreconciled_projected_executions:
            fail("projected execution cash movement does not match Schwab")
        if unsafe_single_instrument_strategies:
            fail("single-instrument episode is labelled as a multi-leg strategy")
        if phase1_v2_family_count_mismatches:
            fail("Phase 1 assembly v2 does not contain exactly ten families")
        if phase1_materialized and not counts["phase1_journal_lifecycle_reconciliation_runs"]:
            fail("Phase 1 materialization lacks lifecycle reconciliation")
        if phase1_lifecycle_run_count_mismatches:
            fail("Phase 1 lifecycle reconciliation counts do not match states")
        if orphaned_phase1_lifecycle_links:
            fail("orphaned Phase 1 lifecycle reconciliation lineage found")
        if unreconciled_phase1_episodes:
            fail("Phase 1 materialized episodes lack lifecycle reconciliation")
        if invalid_history_revision_counts:
            fail("history revision counts do not match immutable snapshot rows")
        if duplicate_current_revision_fills:
            fail("current history revision contains duplicate fill identities")
        if invalid_current_revision_selection:
            fail("history revision activation does not select exactly one current revision")

    finally:
        con.close()

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
