#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class ReconciliationIssue:
    severity: str
    scope: str
    description: str


def _side_sign(side: str) -> Decimal:
    normalized = side.strip().upper()
    if normalized in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return Decimal("1")
    if normalized in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return Decimal("-1")
    raise ValueError(f"unsupported fill side for reconciliation: {side}")


def _position_key(
    source_broker: str,
    source_account_id: str,
    asset_class: str,
    symbol: str,
    option_symbol: str | None,
    underlying_symbol: str | None,
    option_type: str | None,
    expiry: date | None,
    strike,
    multiplier,
    asof_date: date,
) -> tuple:
    return (
        source_broker,
        source_account_id,
        asset_class,
        symbol,
        option_symbol or "",
        underlying_symbol or "",
        option_type or "",
        expiry or date.min,
        strike,
        multiplier,
        asof_date,
    )


def _amount_from_fill(side: str, quantity: Decimal, fill_price: Decimal, multiplier: Decimal | None, commission: Decimal, fees: Decimal) -> Decimal:
    normalized = side.strip().upper()
    multi = multiplier if multiplier is not None else Decimal("1")
    gross = quantity * fill_price * multi
    fee_total = commission + fees
    if normalized in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return -(gross + fee_total)
    if normalized in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return gross - fee_total
    raise ValueError(f"unsupported fill side for reconciliation: {side}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check journal family reconciliation integrity.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb", help="DuckDB journal path.")
    parser.add_argument("--asof", required=False, help="Optional as-of date in YYYY-MM-DD format.")
    parser.add_argument(
        "--policy",
        default="publish",
        choices=("publish", "strict", "report"),
        help=(
            "publish: fail only on BLOCKERs; strict: fail on BLOCKER+WARNING; "
            "report: never fail on mismatch"
        ),
    )
    return parser.parse_args()


def _resolve_asof(con: duckdb.DuckDBPyConnection, asof: str | None) -> date:
    if asof:
        return date.fromisoformat(asof)
    row = con.execute("SELECT max(asof_date) FROM normalized_fills").fetchone()
    max_asof = row[0] if row else None
    if max_asof is None:
        raise RuntimeError("no normalized fills found; cannot determine reconciliation scope")
    return max_asof


def _classify_failures(issues: list[ReconciliationIssue], policy: str) -> int:
    if not issues:
        return 0
    if policy == "report":
        return 0
    if policy == "publish":
        return 1 if any(i.severity == "BLOCKER" for i in issues) else 0
    if policy == "strict":
        return 1 if issues else 0
    return 1


def _query_scalar(con: duckdb.DuckDBPyConnection, sql: str, *params: object) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)

    print("===== OneJournal Journal Reconciliation Check =====")
    print(f"DB      : {db_path}")
    print(f"POLICY  : {args.policy}")
    print(f"AUTO    : disabled")

    if not db_path.exists():
        print("STATUS  : failed missing DB")
        return 1

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        for required in ("import_runs", "normalized_fills", "normalized_accounts", "normalized_positions", "normalized_transactions"):
            if con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [required]).fetchone() is None:
                print(f"STATUS  : failed missing required table {required}")
                return 1

        asof = _resolve_asof(con, args.asof)
        print(f"ASOF    : {asof}")

        fill_rows = con.execute(
            """
            SELECT
                source_broker, source_account_id, source_fill_id, asof_date,
                asset_class, symbol, option_symbol, underlying_symbol, option_type,
                expiry, strike, multiplier, currency, side, quantity, fill_price,
                commission, fees
            FROM normalized_fills
            WHERE asof_date = ?
            """,
            [asof],
        ).fetchall()

        if not fill_rows:
            print("STATUS  : failed no fills found for asof")
            return 1

        expected_positions: dict[tuple, Decimal] = {}
        expected_tx_by_fill: dict[tuple, int] = {}
        expected_cash: dict[tuple, Decimal] = {}
        fill_accounts = set[tuple[str, str]]()
        for row in fill_rows:
            (
                source_broker,
                source_account_id,
                source_fill_id,
                _fill_asof,
                asset_class,
                symbol,
                option_symbol,
                underlying_symbol,
                option_type,
                expiry,
                strike,
                multiplier,
                currency,
                side,
                quantity,
                fill_price,
                commission,
                fees,
            ) = row
            key = _position_key(
                source_broker,
                source_account_id,
                asset_class,
                symbol,
                option_symbol,
                underlying_symbol,
                option_type,
                expiry,
                strike,
                multiplier,
                asof,
            )
            fill_accounts.add((source_broker, source_account_id))
            expected_positions[key] = expected_positions.get(key, Decimal("0")) + (
                _side_sign(side) * quantity
            )

            fill_key = (source_broker, source_account_id, source_fill_id)
            expected_tx_by_fill[fill_key] = expected_tx_by_fill.get(fill_key, 0) + 1

            tx_key = (source_broker, source_account_id, currency)
            expected_cash[tx_key] = expected_cash.get(tx_key, Decimal("0")) + _amount_from_fill(
                side,
                quantity,
                fill_price,
                multiplier,
                commission,
                fees,
            )

        tx_rows = con.execute(
            """
            SELECT
                source_broker, source_account_id, transaction_type,
                COALESCE(currency, ''), COALESCE(linked_fill_id, ''),
                COALESCE(transaction_type, ''), amount
            FROM normalized_transactions
            WHERE asof_date = ?
            """,
            [asof],
        ).fetchall()

        issues: list[ReconciliationIssue] = []

        tx_by_fill: dict[tuple, int] = {}
        tx_by_scope: dict[tuple, Decimal] = {}
        for source_broker, source_account_id, _t_type, currency, linked_fill_id, transaction_type, amount in tx_rows:
            tx_key = (source_broker, source_account_id, linked_fill_id)
            if transaction_type.upper() == "FILL":
                tx_by_fill[tx_key] = tx_by_fill.get(tx_key, 0) + 1
            else:
                if linked_fill_id == "":
                    issues.append(
                        ReconciliationIssue(
                            "WARNING",
                            "transaction",
                            f"non-fill transaction for {source_broker}:{source_account_id} has no linked_fill_id",
                        )
                    )
                elif tx_key not in expected_tx_by_fill:
                    issues.append(
                        ReconciliationIssue(
                            "WARNING",
                            "transaction",
                            f"non-fill transaction {tx_key} has no corresponding fill in asof {asof}",
                        )
                    )
            tx_by_scope[(source_broker, source_account_id, currency)] = tx_by_scope.get(
                (source_broker, source_account_id, currency),
                Decimal("0"),
            ) + amount

        position_rows = con.execute(
            """
            SELECT
                source_broker, source_account_id, asof_date, asset_class,
                symbol, option_symbol, underlying_symbol, option_type,
                expiry, strike, multiplier, quantity
            FROM normalized_positions
            WHERE asof_date = ?
            """,
            [asof],
        ).fetchall()

        account_rows = con.execute(
            "SELECT source_broker, source_account_id FROM normalized_accounts WHERE asof_date = ?",
            [asof],
        ).fetchall()
        account_rows_set = {(row[0], row[1]) for row in account_rows}

        for fill_key, expected_count in expected_tx_by_fill.items():
            observed = tx_by_fill.get(fill_key, 0)
            if observed != expected_count:
                issues.append(
                    ReconciliationIssue(
                        "BLOCKER",
                        "transaction",
                        f"fill {fill_key} expected {expected_count} fill transaction(s), observed {observed}",
                    )
                )

        for tx_key, observed in tx_by_fill.items():
            if tx_key[2] == "":
                issues.append(
                    ReconciliationIssue(
                        "WARNING",
                        "transaction",
                        f"transaction for fill scope {tx_key} is missing linked_fill_id",
                    )
                )
                continue
            if tx_key not in expected_tx_by_fill:
                issues.append(
                    ReconciliationIssue(
                        "WARNING",
                        "transaction",
                        f"transaction-linked fill {tx_key} has no corresponding fill in asof {asof}",
                    )
                )

        position_rows_map = {
            _position_key(
                source_broker,
                source_account_id,
                asset_class,
                symbol,
                option_symbol,
                underlying_symbol,
                option_type,
                expiry,
                strike,
                multiplier,
                asof_date,
            ): (source_broker, source_account_id, symbol, quantity)
            for (
                source_broker,
                source_account_id,
                asof_date,
                asset_class,
                symbol,
                option_symbol,
                underlying_symbol,
                option_type,
                expiry,
                strike,
                multiplier,
                quantity,
            ) in position_rows
        }

        for key, expected_qty in expected_positions.items():
            observed_qty = position_rows_map.get(key)
            if observed_qty is None:
                issues.append(
                    ReconciliationIssue(
                        "BLOCKER",
                        "position",
                        f"missing normalized_position for scope {key}",
                    )
                )
                continue
            scope_broker, scope_account, scope_symbol, observed_qty = observed_qty
            _ = scope_broker, scope_account, scope_symbol
            if observed_qty != expected_qty:
                issues.append(
                    ReconciliationIssue(
                        "BLOCKER",
                        "position",
                        f"position mismatch for {key[0:2]}/{key[3]}: expected {expected_qty}, observed {observed_qty}",
                    )
                )

        for key in position_rows_map:
            if key not in expected_positions:
                issues.append(
                    ReconciliationIssue(
                        "WARNING",
                        "position",
                        f"normalized_position exists without source fill coverage: {key}",
                    )
                )

        for key, expected_amount in expected_cash.items():
            observed_amount = tx_by_scope.get(key, Decimal("0"))
            if observed_amount != expected_amount:
                issues.append(
                    ReconciliationIssue(
                        "BLOCKER",
                        "cash",
                        f"cashflow mismatch for {key[0]}:{key[1]} {key[2]}: expected {expected_amount}, observed {observed_amount}",
                    )
                )

        for key, observed_amount in tx_by_scope.items():
            if key not in expected_cash and observed_amount != Decimal("0"):
                issues.append(
                    ReconciliationIssue(
                        "WARNING",
                        "cash",
                        f"transaction flow without fill-derived expectation for {key[0]}:{key[1]} {key[2]}: observed {observed_amount}",
                    )
                )

        for acct_key in fill_accounts:
            if acct_key not in account_rows_set:
                issues.append(
                    ReconciliationIssue(
                        "BLOCKER",
                        "account",
                        f"fill account {acct_key} missing normalized_account row",
                    )
                )

        for acct_key in account_rows_set:
            if acct_key not in fill_accounts:
                if _query_scalar(
                    con,
                    "SELECT COUNT(*) FROM normalized_fills WHERE source_broker = ? AND source_account_id = ?",
                    acct_key[0],
                    acct_key[1],
                ):
                    continue
                issues.append(
                    ReconciliationIssue(
                        "WARNING",
                        "account",
                        f"normalized_account {acct_key} has no fills for asof {asof}",
                    )
                )

        print("")
        print(f"NORMALIZED_FILLS      : {_query_scalar(con, 'SELECT COUNT(*) FROM normalized_fills WHERE asof_date = ?', asof)}")
        print(f"NORMALIZED_TRANSACTIONS: {_query_scalar(con, 'SELECT COUNT(*) FROM normalized_transactions WHERE asof_date = ?', asof)}")
        print(f"NORMALIZED_POSITIONS   : {_query_scalar(con, 'SELECT COUNT(*) FROM normalized_positions WHERE asof_date = ?', asof)}")
        print(f"NORMALIZED_ACCOUNTS    : {_query_scalar(con, 'SELECT COUNT(*) FROM normalized_accounts WHERE asof_date = ?', asof)}")
        print(f"ISSUES               : {len(issues)}")

        for issue in issues:
            print(f"{issue.severity:8s}: {issue.scope:10s}: {issue.description}")

        rc = _classify_failures(issues, args.policy)
        print("")
        print("===== Result =====")
        print(f"STATUS    : {'failed' if rc else 'OK'}")
        return rc
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
