from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

REQUIRED_IMPORT_RUN_COLUMNS = {
    "import_run_id",
    "source_type",
    "source_path",
    "asof_date",
    "imported_at",
    "row_count",
    "status",
    "notes",
}

NORMALIZED_TABLES = (
    "normalized_fills",
    "normalized_accounts",
    "normalized_orders",
    "normalized_positions",
    "normalized_transactions",
    "normalized_lifecycle_events",
)


def _query_scalar_int(con: duckdb.DuckDBPyConnection, sql: str, *params: object) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OneJournal import_runs audit integrity.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb", help="DuckDB journal database path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)

    print("===== OneJournal import run audit check =====")
    print(f"DB        : {db_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")

    failures: list[str] = []

    if not db_path.exists():
        print()
        print("===== Result =====")
        print("STATUS    : failed missing DB")
        return 1

    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        for table in ("import_runs", "normalized_fills"):
            if table not in tables:
                failures.append(f"missing table {table}")
        for table in NORMALIZED_TABLES:
            if table not in tables:
                failures.append(f"missing table {table}")

        if failures:
            print()
            print("===== Result =====")
            print("STATUS    : failed import audit contract")
            for failure in failures:
                print(f"FAIL      : {failure}")
            return 1

        import_cols = {row[1] for row in con.execute("PRAGMA table_info(import_runs)").fetchall()}
        missing_cols = sorted(REQUIRED_IMPORT_RUN_COLUMNS - import_cols)
        for col in missing_cols:
            failures.append(f"import_runs missing column {col}")

        import_count = con.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0]
        fill_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_fills")
        account_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_accounts")
        order_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_orders")
        position_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_positions")
        transaction_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_transactions")
        lifecycle_count = _query_scalar_int(con, "SELECT COUNT(*) FROM normalized_lifecycle_events")

        blank_required = con.execute(
            """
            SELECT COUNT(*)
            FROM import_runs
            WHERE COALESCE(import_run_id, '') = ''
               OR COALESCE(source_type, '') = ''
               OR COALESCE(source_path, '') = ''
               OR asof_date IS NULL
               OR imported_at IS NULL
               OR row_count IS NULL
               OR row_count <= 0
               OR COALESCE(status, '') = ''
            """
        ).fetchone()[0]

        non_ok_status = con.execute(
            """
            SELECT COUNT(*)
            FROM import_runs
            WHERE lower(status) NOT IN (?, ?, ?)
            """,
            ("ok", "success", "completed"),
        ).fetchone()[0]

        missing_fill_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_fills
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_fill_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_fills f
            LEFT JOIN import_runs r ON r.import_run_id = f.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        missing_account_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_accounts
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_account_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_accounts a
            LEFT JOIN import_runs r ON r.import_run_id = a.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        missing_order_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_orders
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_order_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_orders o
            LEFT JOIN import_runs r ON r.import_run_id = o.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        missing_position_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_positions
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_position_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_positions p
            LEFT JOIN import_runs r ON r.import_run_id = p.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        missing_transaction_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_transactions
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_transaction_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_transactions t
            LEFT JOIN import_runs r ON r.import_run_id = t.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        missing_lifecycle_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_events e
            WHERE COALESCE(import_run_id, '') = ''
            """
        ).fetchone()[0]

        orphan_lifecycle_import_id = con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_events e
            LEFT JOIN import_runs r ON r.import_run_id = e.import_run_id
            WHERE r.import_run_id IS NULL
            """
        ).fetchone()[0]

        if import_count <= 0:
            failures.append("import_runs has no rows")
        if fill_count <= 0:
            failures.append("normalized_fills has no rows")
        if account_count <= 0:
            failures.append("normalized_accounts has no rows")
        if order_count <= 0:
            failures.append("normalized_orders has no rows")
        if position_count <= 0:
            failures.append("normalized_positions has no rows")
        if transaction_count <= 0:
            failures.append("normalized_transactions has no rows")
        if blank_required:
            failures.append(f"import_runs has {blank_required} row(s) with missing required audit fields")
        if non_ok_status:
            failures.append(f"import_runs has {non_ok_status} row(s) with non-ok status")
        if missing_fill_import_id:
            failures.append(f"normalized_fills has {missing_fill_import_id} row(s) without import_run_id")
        if orphan_fill_import_id:
            failures.append(f"normalized_fills has {orphan_fill_import_id} row(s) with orphan import_run_id")
        if missing_account_import_id:
            failures.append(f"normalized_accounts has {missing_account_import_id} row(s) without import_run_id")
        if orphan_account_import_id:
            failures.append(f"normalized_accounts has {orphan_account_import_id} row(s) with orphan import_run_id")
        if missing_order_import_id:
            failures.append(f"normalized_orders has {missing_order_import_id} row(s) without import_run_id")
        if orphan_order_import_id:
            failures.append(f"normalized_orders has {orphan_order_import_id} row(s) with orphan import_run_id")
        if missing_position_import_id:
            failures.append(f"normalized_positions has {missing_position_import_id} row(s) without import_run_id")
        if orphan_position_import_id:
            failures.append(f"normalized_positions has {orphan_position_import_id} row(s) with orphan import_run_id")
        if missing_transaction_import_id:
            failures.append(f"normalized_transactions has {missing_transaction_import_id} row(s) without import_run_id")
        if orphan_transaction_import_id:
            failures.append(f"normalized_transactions has {orphan_transaction_import_id} row(s) with orphan import_run_id")
        if missing_lifecycle_import_id:
            failures.append(f"normalized_lifecycle_events has {missing_lifecycle_import_id} row(s) without import_run_id")
        if orphan_lifecycle_import_id:
            failures.append(f"normalized_lifecycle_events has {orphan_lifecycle_import_id} row(s) with orphan import_run_id")

        print()
        print("===== Counts =====")
        print(f"IMPORT_RUNS       : {import_count}")
        print(f"NORMALIZED_FILLS  : {fill_count}")
        print(f"NORMALIZED_ACCOUNTS: {account_count}")
        print(f"NORMALIZED_ORDERS : {order_count}")
        print(f"NORMALIZED_POSITIONS: {position_count}")
        print(f"NORMALIZED_TRANSACTIONS: {transaction_count}")
        print(f"NORMALIZED_LIFECYCLE_EVENTS: {lifecycle_count}")
        print(f"BLANK_REQUIRED    : {blank_required}")
        print(f"NON_OK_STATUS     : {non_ok_status}")
        print(f"MISSING_IMPORT_ID : {missing_fill_import_id}")
        print(f"ORPHAN_IMPORT_ID  : {orphan_fill_import_id}")
        print(f"MISSING_ACCT_ID : {missing_account_import_id}")
        print(f"ORPHAN_ACCT_ID  : {orphan_account_import_id}")
        print(f"MISSING_ORDER_ID : {missing_order_import_id}")
        print(f"ORPHAN_ORDER_ID  : {orphan_order_import_id}")
        print(f"MISSING_POSITION_ID : {missing_position_import_id}")
        print(f"ORPHAN_POSITION_ID  : {orphan_position_import_id}")
        print(f"MISSING_TXN_ID : {missing_transaction_import_id}")
        print(f"ORPHAN_TXN_ID  : {orphan_transaction_import_id}")
        print(f"MISSING_LIFECYCLE_ID : {missing_lifecycle_import_id}")
        print(f"ORPHAN_LIFECYCLE_ID  : {orphan_lifecycle_import_id}")

    print()
    print("===== Result =====")
    if failures:
        print("STATUS    : failed import audit contract")
        for failure in failures:
            print(f"FAIL      : {failure}")
        return 1

    print("STATUS    : OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
