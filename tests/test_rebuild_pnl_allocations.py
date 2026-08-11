from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import duckdb

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.pnl import build_instrument_key
from scripts.journal.import_journal_to_db import import_to_db
from scripts.journal.init_journal_db import init_schema
from scripts.journal.rebuild_pnl_allocations import build_pnl_allocations
from scripts.journal.build_dashboard_payload_from_db import build_payload


class RebuildPnLAllocationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "journal.duckdb"
        self.fills_path = self.root / "fills.csv"
        self.reviews_path = self.root / "reviews.csv"
        self.events_path = self.root / "events.csv"
        self.legs_path = self.root / "legs.csv"
        self.instructions_path = self.root / "instructions.csv"
        init_schema(self.db_path)

        self.fills_path.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,open_close
2026-07-17,manual_csv,DEMO_ACCOUNT,OPT-OPEN,2026-07-17T10:00:00Z,option,AAPL  260717C00100000,BUY_TO_OPEN,1,2,1,0,USD,ORDER-1,AAPL  260717C00100000,AAPL,CALL,2026-07-17,100,100,OPEN
""",
            encoding="utf-8",
        )
        self.reviews_path.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n",
            encoding="utf-8",
        )
        self.events_path.write_text(
            """event_uid,source_broker,source_account_id,source_activity_id,source_order_id,source_position_id,event_class,event_type,asof,event_at,event_name
event:expiration,manual_csv,DEMO_ACCOUNT,ACT-EXP,,,TRANSACTION_LIFECYCLE,activityType:EXPIRATION,2026-07-17,2026-07-17T20:00:00Z,expiration
""",
            encoding="utf-8",
        )
        self.legs_path.write_text(
            """event_leg_uid,event_uid,leg_index,leg_kind,asset_class,symbol,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,signed_quantity,price,cash_amount,position_effect,fee_type,currency,deliverable_json,evidence_status,evidence_notes
event:expiration:item:0,event:expiration,0,security,option,AAPL,AAPL  260717C00100000,AAPL,CALL,2026-07-17,100,100,-1,0,0,CLOSING,,USD,,observed,
""",
            encoding="utf-8",
        )
        import_to_db(
            self.db_path,
            self.fills_path,
            self.reviews_path,
            replace=True,
            lifecycle_events=self.events_path,
            lifecycle_event_legs=self.legs_path,
            asof=date(2026, 7, 17),
        )
        fill = parse_manual_fills_csv(self.fills_path)[0]
        self.fill_uid = fill.fill_uid
        self.option_instrument_key = build_instrument_key(fill)
        self._write_instruction()

    def _write_instruction(
        self,
        *,
        evidence_status: str = "approved",
        event_fees: str = "0",
    ) -> None:
        fields = [
            "event_uid",
            "event_type",
            "source_broker",
            "source_account_id",
            "currency",
            "effective_at",
            "option_instrument_key",
            "predecessor_direction",
            "contracts",
            "predecessor_open_fill_uids_json",
            "event_commission",
            "event_fees",
            "evidence_status",
            "source_event_leg_uids_json",
            "successor_action",
            "successor_position_effect",
            "successor_symbol",
            "successor_quantity",
            "strike_cash_amount",
            "reviewed_at",
            "review_source",
        ]
        with self.instructions_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "event_uid": "event:expiration",
                    "event_type": "EXPIRATION",
                    "source_broker": "manual_csv",
                    "source_account_id": "DEMO_ACCOUNT",
                    "currency": "USD",
                    "effective_at": "2026-07-17T20:00:00Z",
                    "option_instrument_key": self.option_instrument_key,
                    "predecessor_direction": "LONG",
                    "contracts": "1",
                    "predecessor_open_fill_uids_json": f'["{self.fill_uid}"]',
                    "event_commission": "0",
                    "event_fees": event_fees,
                    "evidence_status": evidence_status,
                    "source_event_leg_uids_json": '["event:expiration:item:0"]',
                    "successor_action": "",
                    "successor_position_effect": "",
                    "successor_symbol": "",
                    "successor_quantity": "",
                    "strike_cash_amount": "",
                    "reviewed_at": "2026-07-18T01:00:00Z",
                    "review_source": "owner_review",
                }
            )

    def _count(self, table: str) -> int:
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_dry_run_validates_without_database_writes(self) -> None:
        before_fills = self._count("normalized_fills")

        summary = build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=False,
        )

        self.assertFalse(summary.applied)
        self.assertEqual(summary.lifecycle_allocation_count, 1)
        self.assertEqual(self._count("pnl_calculation_runs"), 0)
        self.assertEqual(self._count("approved_option_lifecycle_events"), 0)
        self.assertEqual(self._count("normalized_fills"), before_fills)

    def test_apply_appends_approval_and_versioned_calculation_run(self) -> None:
        first = build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )
        second = build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )

        self.assertTrue(first.applied)
        self.assertNotEqual(first.calculation_run_id, second.calculation_run_id)
        self.assertEqual(self._count("approved_option_lifecycle_events"), 1)
        self.assertEqual(self._count("pnl_calculation_runs"), 2)
        self.assertEqual(self._count("pnl_lifecycle_allocations"), 2)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT net_option_basis, realized_pnl, successor_fill_uid
                FROM pnl_lifecycle_allocations
                WHERE calculation_run_id = ?
                """,
                (first.calculation_run_id,),
            ).fetchone()
            self.assertEqual(row, (201, -201, None))
            group = con.execute(
                """
                SELECT open_quantity, realized_pnl
                FROM pnl_group_results
                WHERE calculation_run_id = ? AND instrument_key = ?
                """,
                (first.calculation_run_id, self.option_instrument_key),
            ).fetchone()
            self.assertEqual(group, (0, -201))

    def test_review_required_instruction_fails_before_writing(self) -> None:
        self._write_instruction(evidence_status="review_required")

        with self.assertRaisesRegex(ValueError, "not approved evidence"):
            build_pnl_allocations(
                self.db_path,
                self.instructions_path,
                asof=date(2026, 7, 17),
                apply=True,
            )

        self.assertEqual(self._count("pnl_calculation_runs"), 0)
        self.assertEqual(self._count("approved_option_lifecycle_events"), 0)

    def test_conflicting_reapproval_is_rejected_without_overwrite(self) -> None:
        build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )
        self._write_instruction(event_fees="1")

        with self.assertRaisesRegex(ValueError, "corrections require a linked corrective event"):
            build_pnl_allocations(
                self.db_path,
                self.instructions_path,
                asof=date(2026, 7, 17),
                apply=True,
            )

        self.assertEqual(self._count("approved_option_lifecycle_events"), 1)
        self.assertEqual(self._count("pnl_calculation_runs"), 1)

    def test_missing_utc_fill_evidence_blocks_calculation(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            con.execute("UPDATE normalized_fills SET filled_at_utc = NULL")

        with self.assertRaisesRegex(ValueError, "legacy timestamp backfill is required"):
            build_pnl_allocations(
                self.db_path,
                self.instructions_path,
                asof=date(2026, 7, 17),
                apply=False,
            )

    def test_replace_import_cannot_orphan_approved_pnl_lineage(self) -> None:
        build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )

        with self.assertRaisesRegex(
            ValueError,
            "--replace would invalidate approved lifecycle/P&L lineage",
        ):
            import_to_db(
                self.db_path,
                self.fills_path,
                self.reviews_path,
                replace=True,
                lifecycle_events=self.events_path,
                lifecycle_event_legs=self.legs_path,
                asof=date(2026, 7, 17),
            )

        self.assertEqual(self._count("approved_option_lifecycle_events"), 1)
        self.assertEqual(self._count("pnl_calculation_runs"), 1)

    def test_dashboard_uses_only_current_fingerprint_matched_pnl_run(self) -> None:
        applied = build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )

        current = build_payload(self.db_path, "2026-07-17")
        pnl_quality = current["metadata"]["quality"]["checks"]["pnl"]
        lifecycle_quality = current["metadata"]["quality"]["checks"][
            "lifecycle_evidence"
        ]
        self.assertEqual(current["trade_summary"]["realized_pnl_by_currency"], {"USD": "-201.00"})
        self.assertEqual(pnl_quality["status"], "valid")
        self.assertEqual(pnl_quality["calculation_run_id"], applied.calculation_run_id)
        self.assertEqual(lifecycle_quality["allocated_event_count"], 1)
        self.assertEqual(lifecycle_quality["unallocated_event_count"], 0)

        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                "UPDATE normalized_fills SET commission = commission + 1 WHERE fill_uid = ?",
                (self.fill_uid,),
            )

        stale = build_payload(self.db_path, "2026-07-17")
        stale_pnl_quality = stale["metadata"]["quality"]["checks"]["pnl"]
        self.assertEqual(stale_pnl_quality["status"], "incomplete")
        self.assertIsNone(stale_pnl_quality["calculation_run_id"])
        self.assertEqual(stale_pnl_quality["unallocated_lifecycle_event_count"], 1)

    def test_reconciliation_accepts_current_allocated_lifecycle_event(self) -> None:
        applied = build_pnl_allocations(
            self.db_path,
            self.instructions_path,
            asof=date(2026, 7, 17),
            apply=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                "scripts/journal/check_journal_reconciliation.py",
                "--db",
                str(self.db_path),
                "--asof",
                "2026-07-17",
                "--policy",
                "publish",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LIFECYCLE_ALLOCATED    : 1", result.stdout)
        self.assertIn(f"CURRENT_PNL_RUN        : {applied.calculation_run_id}", result.stdout)

        health = subprocess.run(
            [
                sys.executable,
                "scripts/journal/check_journal_db.py",
                "--db",
                str(self.db_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(health.returncode, 0, health.stdout + health.stderr)
        self.assertIn("pnl_run_count_mismatches: 0", health.stdout)


if __name__ == "__main__":
    unittest.main()
