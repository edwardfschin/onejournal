from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.schwab_lifecycle_presentation import (
    LIFECYCLE_PRESENTATION_CONTRACT_VERSION,
    lifecycle_presentation_to_dict,
    load_schwab_lifecycle_presentations,
)


class SchwabLifecyclePresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "lifecycle.duckdb"
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                "CREATE TABLE normalized_fills "
                "(fill_uid VARCHAR, source_account_id VARCHAR, open_close VARCHAR)"
            )
            con.execute(
                """
                CREATE TABLE phase1_journal_projected_episodes (
                    projection_uid VARCHAR, episode_uid VARCHAR,
                    strategy_type VARCHAR, strategy_label VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE phase1_journal_projected_instruments (
                    projection_uid VARCHAR, episode_uid VARCHAR,
                    instrument_uid VARCHAR, asset_class VARCHAR, symbol VARCHAR,
                    option_type VARCHAR, expiry DATE, strike DECIMAL(20,6),
                    multiplier DECIMAL(20,6), opening_direction VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE phase1_journal_projected_executions (
                    projection_uid VARCHAR, episode_uid VARCHAR,
                    instrument_uid VARCHAR, execution_uid VARCHAR,
                    fill_uid VARCHAR, filled_at_utc VARCHAR, side VARCHAR,
                    quantity DECIMAL(20,6), fill_price DECIMAL(20,6),
                    schwab_net_cash_movement DECIMAL(20,6),
                    commission DECIMAL(20,6), fees DECIMAL(20,6),
                    currency VARCHAR, execution_index INTEGER
                )
                """
            )
            con.execute(
                "CREATE TABLE trade_episodes "
                "(episode_uid VARCHAR, primary_symbol VARCHAR, opened_at TIMESTAMP)"
            )
            con.execute(
                """
                CREATE TABLE phase1_journal_lifecycle_reconciliation_runs (
                    reconciliation_uid VARCHAR, assembly_uid VARCHAR,
                    asof_date DATE, reconciled_at TIMESTAMP
                )
                """
            )
            con.execute(
                "CREATE TABLE phase1_journal_episode_lifecycle_states "
                "(reconciliation_uid VARCHAR, episode_uid VARCHAR, "
                "reconciled_status VARCHAR, lifecycle_quality VARCHAR, "
                "reason_code VARCHAR, position_reconciliation_status VARCHAR, "
                "matched_terminal_event_count INTEGER)"
            )
            con.execute(
                "CREATE TABLE phase1_schwab_evidence_v2_import_families "
                "(assembly_uid VARCHAR, family VARCHAR, records_json VARCHAR)"
            )
            con.execute(
                "INSERT INTO phase1_journal_lifecycle_reconciliation_runs "
                "VALUES ('recon-1','assembly-1',DATE '2026-09-04',"
                "TIMESTAMP '2026-09-06 12:00:00')"
            )
            self._episode(
                con,
                episode_uid="eypt-option",
                symbol="EYPT",
                asset_class="option",
                strategy_type="sell_put",
                strategy_label="Sell Put",
                option_type="PUT",
                expiry="2026-09-18",
                strike="5",
                multiplier="100",
                direction="SHORT",
                status="closed",
                executions=(
                    ("eypt-open", "2026-08-13T14:18:24Z", "SELL", "5", ".90", "446.65", "open"),
                    ("eypt-close", "2026-08-17T13:51:05Z", "BUY", "5", "1.09", "-548.32", "close"),
                ),
            )
            self._episode(
                con,
                episode_uid="xpev-option",
                symbol="XPEV",
                asset_class="option",
                strategy_type="sell_put",
                strategy_label="Sell Put",
                option_type="PUT",
                expiry="2026-08-28",
                strike="16",
                multiplier="100",
                direction="SHORT",
                status="review_required",
                executions=(("xpev-open", "2026-08-12T13:33:19Z", "SELL", "2", "4.30", "858.64", "open"),),
            )
            self._episode(
                con,
                episode_uid="xpev-stock",
                symbol="XPEV",
                asset_class="stock",
                strategy_type="stock_long",
                strategy_label="Stock Long",
                option_type=None,
                expiry=None,
                strike=None,
                multiplier=None,
                direction="LONG",
                status="review_required",
                executions=(("xpev-stock-open", "2026-08-25T04:00:00Z", "BUY", "200", "16", "-3200", "open"),),
            )
            self._episode(
                con,
                episode_uid="tri-option",
                symbol="TRI",
                asset_class="option",
                strategy_type="sell_put",
                strategy_label="Sell Put",
                option_type="PUT",
                expiry="2026-08-21",
                strike="80",
                multiplier="100",
                direction="SHORT",
                status="closed",
                lifecycle_quality="review_required",
                lifecycle_reason="broker_terminal_event_review_required",
                position_status="terminal_reconciled",
                matched_terminal_event_count=1,
                executions=(("tri-open", "2026-06-18T13:41:00Z", "SELL", "2", "1.60", "318.66", "open"),),
            )
            self._episode(
                con,
                episode_uid="msft-option",
                symbol="MSFT",
                asset_class="option",
                strategy_type="sell_call",
                strategy_label="Sell Call",
                option_type="CALL",
                expiry="2026-08-07",
                strike="460",
                multiplier="100",
                direction="SHORT",
                status="review_required",
                executions=(("msft-open", "2026-07-30T13:45:14Z", "SELL", "1", "7", "699.33", "open"),),
            )
            self._episode(
                con,
                episode_uid="msft-stock",
                symbol="MSFT",
                asset_class="stock",
                strategy_type="stock_long",
                strategy_label="Stock Long",
                option_type=None,
                expiry=None,
                strike=None,
                multiplier=None,
                direction="LONG",
                status="review_required",
                executions=(("msft-stock-close", "2026-08-10T04:00:00Z", "SELL", "100", "460", "46000", "close"),),
            )
            self._episode(
                con,
                episode_uid="etr-option",
                symbol="ETR",
                asset_class="option",
                strategy_type="unknown",
                strategy_label="Lifecycle Review Required",
                option_type="CALL",
                expiry="2026-09-18",
                strike="105",
                multiplier="100",
                direction="",
                status="review_required",
                lifecycle_quality="review_required",
                lifecycle_reason="history_extension_required",
                executions=(("etr-close", "2026-07-14T13:55:41Z", "SELL", "1", "12.65", "1264.33", "close"),),
            )
            con.execute(
                "INSERT INTO phase1_schwab_evidence_v2_import_families "
                "VALUES ('assembly-1','transactions',?)",
                [json.dumps(self._transactions())],
            )
            con.execute(
                "INSERT INTO phase1_schwab_evidence_v2_import_families "
                "VALUES ('assembly-1','lifecycle_events',?)",
                [json.dumps(self._expiration_events())],
            )
            con.execute(
                "INSERT INTO phase1_schwab_evidence_v2_import_families "
                "VALUES ('assembly-1','lifecycle_event_legs',?)",
                [json.dumps(self._expiration_legs())],
            )

    def _episode(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        episode_uid: str,
        symbol: str,
        asset_class: str,
        strategy_type: str,
        strategy_label: str,
        option_type: str | None,
        expiry: str | None,
        strike: str | None,
        multiplier: str | None,
        direction: str,
        status: str,
        executions: tuple[tuple[str, str, str, str, str, str, str], ...],
        lifecycle_quality: str = "resolved",
        lifecycle_reason: str | None = None,
        position_status: str = "not_applicable",
        matched_terminal_event_count: int = 0,
    ) -> None:
        instrument_uid = f"instrument-{episode_uid}"
        con.execute(
            "INSERT INTO trade_episodes VALUES (?, ?, TIMESTAMP '2026-08-12 13:33:19')",
            [episode_uid, symbol],
        )
        con.execute(
            "INSERT INTO phase1_journal_projected_episodes VALUES ('projection-1',?,?,?)",
            [episode_uid, strategy_type, strategy_label],
        )
        con.execute(
            """
            INSERT INTO phase1_journal_projected_instruments
            VALUES ('projection-1',?,?,?,?,?,CAST(? AS DATE),CAST(? AS DECIMAL(20,6)),
                    CAST(? AS DECIMAL(20,6)),?)
            """,
            [
                episode_uid,
                instrument_uid,
                asset_class,
                symbol,
                option_type,
                expiry,
                strike,
                multiplier,
                direction,
            ],
        )
        con.execute(
            "INSERT INTO phase1_journal_episode_lifecycle_states "
            "VALUES ('recon-1',?,?,?,?,?,?)",
            [
                episode_uid,
                status,
                lifecycle_quality,
                lifecycle_reason,
                position_status,
                matched_terminal_event_count,
            ],
        )
        for index, (fill_uid, at, side, quantity, price, cash, effect) in enumerate(
            executions, start=1
        ):
            con.execute(
                "INSERT INTO normalized_fills VALUES (?, 'private-account-must-not-leak', ?)",
                [fill_uid, effect],
            )
            con.execute(
                """
                INSERT INTO phase1_journal_projected_executions
                VALUES ('projection-1',?,?,?,?,?,?,?,?,?,0,0,'USD',?)
                """,
                [
                    episode_uid,
                    instrument_uid,
                    f"execution-{fill_uid}",
                    fill_uid,
                    at,
                    side,
                    quantity,
                    price,
                    cash,
                    index,
                ],
            )

    @staticmethod
    def _transactions() -> list[dict[str, object]]:
        return [
            {
                "source_account_id": "private-account-must-not-leak",
                "source_transaction_id": "private-option-transaction-must-not-leak",
                "transaction_at_utc": "2026-08-25T04:00:00Z",
                "transaction_type": "RECEIVE_AND_DELIVER",
                "items": [
                    {
                        "provider_asset_type": "OPTION",
                        "provider_symbol": "XPEV  260828P00016000",
                        "amount": "2",
                        "price": "0",
                        "position_effect": "CLOSING",
                    }
                ],
            },
            {
                "source_account_id": "private-account-must-not-leak",
                "source_transaction_id": "private-stock-transaction-must-not-leak",
                "transaction_at_utc": "2026-08-25T04:00:00Z",
                "transaction_type": "TRADE",
                "items": [
                    {
                        "provider_asset_type": "EQUITY",
                        "provider_symbol": "XPEV",
                        "amount": "200",
                        "price": "16",
                        "position_effect": "OPENING",
                    }
                ],
            },
            {
                "source_account_id": "private-account-must-not-leak",
                "source_transaction_id": "private-msft-option-transaction-must-not-leak",
                "transaction_at_utc": "2026-08-10T04:00:00Z",
                "transaction_type": "RECEIVE_AND_DELIVER",
                "items": [
                    {
                        "provider_asset_type": "OPTION",
                        "provider_symbol": "MSFT  260807C00460000",
                        "amount": "1",
                        "price": "0",
                        "position_effect": "CLOSING",
                    }
                ],
            },
            {
                "source_account_id": "private-account-must-not-leak",
                "source_transaction_id": "private-msft-stock-transaction-must-not-leak",
                "transaction_at_utc": "2026-08-10T04:00:00Z",
                "transaction_type": "TRADE",
                "items": [
                    {
                        "provider_asset_type": "EQUITY",
                        "provider_symbol": "MSFT",
                        "amount": "-100",
                        "price": "460",
                        "position_effect": "CLOSING",
                    }
                ],
            },
        ]

    @staticmethod
    def _expiration_events() -> list[dict[str, object]]:
        return [
            {
                "event_uid": "private-expiration-event-must-not-leak",
                "source_account_id": "private-account-must-not-leak",
                "event_class": "TRANSACTION_LIFECYCLE",
                "event_name": "description_hint:EXPIRATION",
                "event_at": "2026-08-24T04:00:00Z",
            }
        ]

    @staticmethod
    def _expiration_legs() -> list[dict[str, object]]:
        return [
            {
                "event_uid": "private-expiration-event-must-not-leak",
                "leg_index": "0",
                "leg_kind": "security",
                "asset_class": "option",
                "symbol": "TRI",
                "underlying_symbol": "TRI",
                "option_type": "PUT",
                "expiry": "2026-08-21",
                "strike": "80",
                "signed_quantity": "2",
                "position_effect": "CLOSING",
                "evidence_status": "review_required",
            }
        ]

    def test_open_and_buy_to_close_are_one_lifecycle_story(self) -> None:
        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }

        eypt = presentations["eypt-option"]
        self.assertEqual(
            eypt.contract_version, LIFECYCLE_PRESENTATION_CONTRACT_VERSION
        )
        self.assertEqual(
            [phase.instruction for phase in eypt.phases],
            ["SELL_TO_OPEN", "BUY_TO_CLOSE"],
        )
        self.assertEqual(eypt.phases[0].quantity, "5")
        self.assertEqual(eypt.phases[1].average_fill_price, "1.09")

    def test_unique_option_stock_settlement_links_assignment_without_ids(self) -> None:
        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }

        outcome = presentations["xpev-option"].option_stock_settlements[0]
        self.assertEqual(outcome.settlement_kind, "assignment")
        self.assertEqual(outcome.option_quantity, "2")
        self.assertEqual(outcome.stock_quantity, "200")
        self.assertEqual(outcome.stock_price, "16")
        self.assertEqual(outcome.stock_episode_uid, "xpev-stock")
        serialized = json.dumps(
            lifecycle_presentation_to_dict(presentations["xpev-option"]),
            default=str,
        )
        self.assertNotIn("private-account-must-not-leak", serialized)
        self.assertNotIn("private-option-transaction-must-not-leak", serialized)
        self.assertNotIn("source_account_id", serialized)
        self.assertNotIn("source_transaction_id", serialized)

    def test_short_call_assignment_links_called_away_closing_stock(self) -> None:
        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }

        outcome = presentations["msft-option"].option_stock_settlements[0]
        self.assertEqual(outcome.settlement_kind, "assignment")
        self.assertEqual(outcome.option_quantity, "1")
        self.assertEqual(outcome.stock_quantity, "-100")
        self.assertEqual(outcome.stock_price, "460")
        self.assertEqual(outcome.stock_episode_uid, "msft-stock")

    def test_close_only_option_exposes_closing_phase_and_missing_history(self) -> None:
        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }

        etr = presentations["etr-option"]
        self.assertEqual(etr.episode_status, "review_required")
        self.assertEqual(etr.history_completeness, "opening_history_missing")
        self.assertEqual(etr.strategy_label, "Buy Call")
        self.assertEqual(len(etr.phases), 1)
        self.assertEqual(etr.phases[0].phase, "closing")
        self.assertEqual(etr.phases[0].instruction, "SELL_TO_CLOSE")

    def test_expiration_hint_links_exact_contract_without_financial_promotion(self) -> None:
        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }

        outcome = presentations["tri-option"].option_expirations[0]
        self.assertEqual(outcome.outcome_kind, "expiration_indicated")
        self.assertEqual(outcome.expires_on.isoformat(), "2026-08-21")
        self.assertEqual(outcome.option_quantity, "2")
        self.assertEqual(outcome.evidence_quality, "review_required")
        serialized = json.dumps(
            lifecycle_presentation_to_dict(presentations["tri-option"]),
            default=str,
        )
        self.assertNotIn("private-account-must-not-leak", serialized)
        self.assertNotIn("private-expiration-event-must-not-leak", serialized)

    def test_ambiguous_stock_match_fails_closed(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            duplicate = self._transactions()[1]
            transactions = self._transactions() + [
                {**duplicate, "source_transaction_id": "another-private-id"}
            ]
            con.execute(
                "UPDATE phase1_schwab_evidence_v2_import_families "
                "SET records_json=? WHERE family='transactions'",
                [json.dumps(transactions)],
            )

        presentations = {
            item.episode_uid: item
            for item in load_schwab_lifecycle_presentations(self.db_path)
        }
        self.assertEqual(
            presentations["xpev-option"].option_stock_settlements, ()
        )


if __name__ == "__main__":
    unittest.main()
