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

        if counts["normalized_fills"] <= 0:
            fail("normalized_fills has no rows")
        if counts["normalized_accounts"] <= 0:
            fail("normalized_accounts has no rows")
        if counts["normalized_orders"] <= 0:
            fail("normalized_orders has no rows")
        if counts["normalized_positions"] <= 0:
            fail("normalized_positions has no rows")
        if counts["normalized_transactions"] <= 0:
            fail("normalized_transactions has no rows")
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

    finally:
        con.close()

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
