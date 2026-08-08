#!/usr/bin/env python3
"""Sequential, resumable Schwab historical raw-evidence fetch operator.

This operator is the live counterpart to the offline D2.2 planner. It uses
only the existing OneJournal-scoped Schwab raw-fetch transport, writes raw JSON
evidence under ``data/raw/schwab``, and writes an operator CSV report. It never
normalizes data, imports DuckDB, or performs a broker order action.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import importlib.util
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

import requests


PROJECT_DIR = Path(__file__).resolve().parents[2]
FETCHER_PATH = PROJECT_DIR / "scripts/journal/fetch_schwab_raw_history.py"
PLANNER_PATH = PROJECT_DIR / "scripts/journal/plan_schwab_raw_history_backfill.py"
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
PROTECTED_START = time(19, 50)
PROTECTED_END = time(20, 30)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load required module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fetcher = load_module("onejournal_schwab_raw_fetcher", FETCHER_PATH)
planner = load_module("onejournal_schwab_backfill_planner", PLANNER_PATH)


@dataclass(frozen=True)
class RawPairPaths:
    orders: Path
    transactions: Path


def raw_pair_paths(fetch_date: date, account_hash: str, window: Any) -> RawPairPaths:
    base = fetcher.RAW_ROOT / fetch_date.isoformat()
    name = f"{account_hash}__{window.start.isoformat()}__{window.end.isoformat()}.json"
    return RawPairPaths(
        orders=base / "orders_all" / name,
        transactions=base / "transactions" / name,
    )


def raw_pair_state(paths: RawPairPaths) -> str:
    orders_exists = paths.orders.exists()
    transactions_exists = paths.transactions.exists()
    if orders_exists and transactions_exists:
        return "complete"
    if orders_exists or transactions_exists:
        return "partial"
    return "missing"


def now_sgt() -> datetime:
    return datetime.now(tz=SINGAPORE_TZ)


def protected_time_active(now: datetime) -> bool:
    local_now = now.astimezone(SINGAPORE_TZ).timetz().replace(tzinfo=None)
    return PROTECTED_START <= local_now < PROTECTED_END


@contextmanager
def single_operator_lock(token_path: Path) -> Iterator[None]:
    """Fail fast if another D2.3 run could refresh the same token in parallel."""

    lock_path = token_path.parent / ".schwab_raw_history_backfill.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"Another Schwab raw-history backfill holds {lock_path}; refusing parallel token use"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def write_report(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "window_number",
        "start",
        "end",
        "days",
        "orders_path",
        "transactions_path",
        "orders_action",
        "transactions_action",
        "status",
        "error",
    ]
    with NamedTemporaryFile(
        "w",
        delete=False,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        newline="",
        encoding="utf-8",
    ) as tf:
        writer = csv.DictWriter(tf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tf.flush()
        os.fsync(tf.fileno())
        temporary_path = Path(tf.name)
    os.replace(temporary_path, path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sequential, resumable Schwab historical raw JSON fetch."
    )
    parser.add_argument("--start", required=True, type=planner.parse_date, help="Inclusive YYYY-MM-DD.")
    parser.add_argument("--end", required=True, type=planner.parse_date, help="Inclusive YYYY-MM-DD.")
    parser.add_argument("--chunk-days", type=int, default=30, help="Maximum inclusive days per window.")
    parser.add_argument(
        "--fetch-date",
        default=datetime.now(tz=SINGAPORE_TZ).date().isoformat(),
        type=planner.parse_date,
        help="Raw snapshot folder date, default today in Asia/Singapore.",
    )
    parser.add_argument("--token-path", default=str(fetcher.DEFAULT_TOKEN_PATH), help="Schwab token JSON path.")
    parser.add_argument("--account-hash", default="", help="Approved Schwab account hash; otherwise discover once.")
    parser.add_argument("--account-index", type=int, default=0, help="Account index when hash is not supplied.")
    parser.add_argument("--max-results", type=int, default=3000, help="Orders maxResults, capped by the transport.")
    parser.add_argument(
        "--report-dir",
        default="output/reports/schwab_raw_history_backfill",
        help="Operator CSV report folder; written only during a live run.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only: no token, network, raw JSON, or report writes.")
    return parser.parse_args(argv)


def print_header(args: argparse.Namespace, windows: list[Any], protected: bool) -> None:
    calls = planner.estimated_api_calls(len(windows))
    print("===== Schwab Raw History Backfill Fetch =====")
    print("MODE                         : dry-run" if args.dry_run else "MODE                         : live raw fetch")
    print("BROKER_HISTORY_REQUESTS      : GET only")
    print("OAUTH_TOKEN_REFRESH          : possible POST")
    print("BROKER_ORDER_WRITE           : disabled")
    print("NORMALIZE_CSV                : disabled")
    print("DUCKDB_WRITE                 : disabled")
    print("SEQUENTIAL_EXECUTION         : enabled")
    print("PARALLEL_TOKEN_REFRESH       : blocked")
    print("RESUME_COMPLETED_PAIRS       : enabled")
    print(f"START                        : {args.start.isoformat()}")
    print(f"END                          : {args.end.isoformat()}")
    print(f"CHUNK_DAYS                   : {args.chunk_days}")
    print(f"FETCH_DATE                   : {args.fetch_date.isoformat()}")
    print(f"WINDOWS_TOTAL                : {len(windows)}")
    print(f"ESTIMATED_GETS_WITH_HASH     : {calls['without_account_lookup']}")
    print(f"ESTIMATED_GETS_WITH_DISCOVERY: {calls['with_account_lookup']}")
    print("TIMEZONE                     : Asia/Singapore")
    print("PROTECTED_TIME               : 19:50-20:30 SGT")
    print(f"PROTECTED_TIME_ACTIVE        : {protected}")
    print(f"DRY_RUN                      : {args.dry_run}")


def select_account_hash(args: argparse.Namespace, client: Any) -> str:
    if args.account_hash.strip():
        print("ACCOUNT_SELECTION            : explicit account hash")
        return args.account_hash.strip()
    accounts = client.account_numbers()
    if args.account_index < 0 or args.account_index >= len(accounts):
        raise RuntimeError(f"account-index {args.account_index} out of range; accounts={len(accounts)}")
    print(f"ACCOUNTS_FOUND                : {len(accounts)}")
    print(f"ACCOUNT_INDEX                 : {args.account_index}")
    return accounts[args.account_index]["hashValue"]


def fetch_missing_evidence(
    client: Any,
    account_hash: str,
    window: Any,
    paths: RawPairPaths,
    max_results: int,
) -> tuple[str, str]:
    """Fetch only missing sides, allowing a failed prior run to resume safely."""

    orders_action = "existing"
    transactions_action = "existing"
    if not paths.orders.exists():
        orders = client.fetch_orders(
            account_hash,
            fetcher.utc_day_start(window.start),
            fetcher.utc_day_end(window.end),
            max_results,
        )
        fetcher.safe_json_write(paths.orders, orders, overwrite=False)
        orders_action = "fetched"
    if not paths.transactions.exists():
        transactions = client.fetch_transactions(
            account_hash,
            fetcher.utc_day_start(window.start),
            fetcher.utc_day_end(window.end),
        )
        fetcher.safe_json_write(paths.transactions, transactions, overwrite=False)
        transactions_action = "fetched"
    return orders_action, transactions_action


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        windows = planner.plan_windows(args.start, args.end, args.chunk_days)
    except ValueError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    protected = protected_time_active(now_sgt())
    token_path = Path(args.token_path).expanduser()
    fetcher.validate_runtime_boundary(token_path)
    print_header(args, windows, protected)
    if args.dry_run:
        print("")
        print("ACTION                       : no token, network, raw JSON, or report writes")
        print("STATUS                       : OK")
        return 0
    if protected:
        print("")
        print("STATUS                       : FAIL")
        print("REASON                       : protected Schwab pre-open time is active")
        return 1

    client_id = os.environ.get("ONEJOURNAL_SCHWAB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("ONEJOURNAL_SCHWAB_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get(
        "ONEJOURNAL_SCHWAB_REDIRECT_URI",
        "https://127.0.0.1:8182/callback",
    ).strip()
    if not client_id:
        print("STATUS                       : FAIL")
        print("REASON                       : ONEJOURNAL_SCHWAB_CLIENT_ID environment variable is required")
        return 1

    report_rows: list[dict[str, object]] = []
    report_path = (
        PROJECT_DIR
        / args.report_dir
        / f"{now_sgt().strftime('%Y%m%d_%H%M%S')}_schwab_raw_history_backfill.csv"
    )
    failed = False

    try:
        with single_operator_lock(token_path):
            auth = fetcher.SchwabAuth(
                store=fetcher.TokenStore(token_path),
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            client = fetcher.SchwabReadOnlyClient(auth=auth, session=requests.Session())
            account_hash = select_account_hash(args, client)

            for number, window in enumerate(windows, start=1):
                paths = raw_pair_paths(args.fetch_date, account_hash, window)
                state = raw_pair_state(paths)
                row: dict[str, object] = {
                    "window_number": number,
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                    "days": window.days,
                    "orders_path": paths.orders.relative_to(PROJECT_DIR),
                    "transactions_path": paths.transactions.relative_to(PROJECT_DIR),
                    "orders_action": "",
                    "transactions_action": "",
                    "status": "",
                    "error": "",
                }
                if state == "complete":
                    row.update(orders_action="existing", transactions_action="existing", status="skipped_complete")
                    print(f"SKIP_COMPLETE                 : window {number:03d} {window.start} to {window.end}")
                    report_rows.append(row)
                    continue

                try:
                    orders_action, transactions_action = fetch_missing_evidence(
                        client,
                        account_hash,
                        window,
                        paths,
                        args.max_results,
                    )
                except Exception as exc:
                    row.update(status="failed", error=str(exc)[:500])
                    print(f"FAILED_WINDOW                 : {number:03d} {window.start} to {window.end}: {exc}")
                    report_rows.append(row)
                    failed = True
                    break

                status = "resumed_partial" if state == "partial" else "fetched"
                row.update(
                    orders_action=orders_action,
                    transactions_action=transactions_action,
                    status=status,
                )
                print(f"{status.upper():<30}: window {number:03d} {window.start} to {window.end}")
                report_rows.append(row)
    except Exception as exc:
        failed = True
        print(f"FAILED_SETUP                  : {exc}")
        report_rows.append(
            {
                "window_number": "",
                "start": "",
                "end": "",
                "days": "",
                "orders_path": "",
                "transactions_path": "",
                "orders_action": "",
                "transactions_action": "",
                "status": "setup_failed",
                "error": str(exc)[:500],
            }
        )

    if report_rows:
        try:
            write_report(report_path, report_rows)
            print(f"REPORT_PATH                   : {report_path.relative_to(PROJECT_DIR)}")
        except Exception as exc:
            failed = True
            print(f"FAILED_REPORT                 : {exc}")
    else:
        failed = True
        print("FAILED_REPORT                 : no report rows available")

    print("")
    print(f"WINDOWS_ATTEMPTED             : {len(report_rows)}")
    print(f"WINDOWS_REMAINING             : {len(windows) - len(report_rows)}")
    print(f"RESUME_COMMAND                : rerun unchanged arguments to skip complete pairs")
    print("STATUS                       : FAIL" if failed else "STATUS                       : OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
