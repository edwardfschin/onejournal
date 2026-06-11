#!/usr/bin/env python3
"""
Fetch Schwab raw orders/transactions JSON into OneJournal ODFS folders.

READ-ONLY GUARANTEE
-------------------
- Uses only GET endpoints.
- Does not write DuckDB.
- Does not normalize CSV.
- Does not place/modify/cancel orders.
- Saves raw JSON evidence only.

Output:
  data/raw/schwab/<fetch_date>/orders_all/<account_hash>__<start>__<end>.json
  data/raw/schwab/<fetch_date>/transactions/<account_hash>__<start>__<end>.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import requests


PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_DIR / "data" / "raw" / "schwab"

SCHWAB_BASE = os.environ.get("SCHWAB_BASE", "https://api.schwabapi.com").rstrip("/")
TRADER_V1 = f"{SCHWAB_BASE}/trader/v1"
OAUTH_TOKEN_URL = f"{SCHWAB_BASE}/v1/oauth/token"
ACCOUNT_NUMBERS_URL = f"{TRADER_V1}/accounts/accountNumbers"

DEFAULT_TOKEN_PATH = Path(
    os.environ.get("TOKEN_PATH", os.path.expanduser("~/.onebot/tokens/schwab_tokens.json"))
)

RESOURCE_VERSION = os.environ.get("SCHWAB_RESOURCE_VERSION", "1")
CLIENT_CORRELID = os.environ.get("SCHWAB_CLIENT_CORRELID", "onejournal-raw-fetch")


def _parse_ymd(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; expected YYYY-MM-DD") from exc


def utc_day_start(d: date) -> str:
    return f"{d.isoformat()}T00:00:00.000Z"


def utc_day_end(d: date) -> str:
    return f"{d.isoformat()}T23:59:59.000Z"


def safe_json_write(path: Path, payload: Any, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing raw file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        delete=False,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        encoding="utf-8",
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False, indent=2, sort_keys=True)
        tf.write("\n")
        tf.flush()
        os.fsync(tf.fileno())
        tmp = tf.name
    os.replace(tmp, path)


@dataclass
class TokenStore:
    path: Path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self, token: dict[str, Any]) -> None:
        if "expires_in" in token and "expires_at" not in token:
            try:
                token["expires_at"] = time.time() + float(token["expires_in"])
            except Exception:
                pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(self.path.parent),
            prefix=self.path.name + ".",
            suffix=".tmp",
            encoding="utf-8",
        ) as tf:
            json.dump(token, tf, ensure_ascii=False, indent=2)
            tf.write("\n")
            tf.flush()
            os.fsync(tf.fileno())
            tmp = tf.name
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            pass

    def is_expired(self, skew_seconds: int = 300) -> bool:
        tok = self.load()
        try:
            exp = float(tok.get("expires_at", 0))
        except Exception:
            return True
        return time.time() >= (exp - skew_seconds)


@dataclass
class SchwabAuth:
    store: TokenStore
    client_id: str
    client_secret: str
    redirect_uri: str

    def get_access_token(self) -> str:
        tok = self.store.load()
        if not tok:
            raise RuntimeError(f"No Schwab token file found at {self.store.path}")
        if self.store.is_expired():
            tok = self.refresh()
        access_token = tok.get("access_token")
        if not access_token:
            raise RuntimeError("Token file has no access_token")
        return str(access_token)

    def refresh(self) -> dict[str, Any]:
        tok = self.store.load()
        refresh_token = tok.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Token file has no refresh_token; re-authorize Schwab first")

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        if self.client_secret:
            headers["Authorization"] = (
                "Basic "
                + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            )
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": self.redirect_uri,
            }
        else:
            data = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
            }

        resp = requests.post(OAUTH_TOKEN_URL, headers=headers, data=data, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Schwab token refresh failed: HTTP {resp.status_code} {resp.text[:300]}")

        payload = resp.json()
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token
        self.store.save(payload)
        return payload


@dataclass
class SchwabReadOnlyClient:
    auth: SchwabAuth
    session: requests.Session
    timeout: int = 60

    def headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "Accept": "application/json",
            "Schwab-Resource-Version": RESOURCE_VERSION,
        }
        if CLIENT_CORRELID:
            h["Schwab-Client-CorrelId"] = CLIENT_CORRELID
        return h

    def get_json(self, url: str, params: dict[str, Any]) -> Any:
        resp = self.session.get(url, headers=self.headers(), params=params, timeout=self.timeout)
        if resp.status_code == 401:
            self.auth.refresh()
            resp = self.session.get(url, headers=self.headers(), params=params, timeout=self.timeout)
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(f"Schwab GET failed: HTTP {resp.status_code} {url} {resp.text[:500]}")
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"Schwab returned non-JSON response from {url}: {resp.text[:500]}") from exc

    def account_numbers(self) -> list[dict[str, str]]:
        data = self.get_json(ACCOUNT_NUMBERS_URL, {})
        if not isinstance(data, list):
            raise RuntimeError("Schwab accountNumbers endpoint did not return a list")
        out: list[dict[str, str]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            account_number = str(row.get("accountNumber", "")).strip()
            hash_value = str(row.get("hashValue", "")).strip()
            if account_number and hash_value:
                out.append({"accountNumber": account_number, "hashValue": hash_value})
        if not out:
            raise RuntimeError("No usable Schwab accounts returned")
        return out

    def fetch_orders(self, account_hash: str, start_iso: str, end_iso: str, max_results: int) -> Any:
        url = f"{TRADER_V1}/accounts/{account_hash}/orders"
        params: dict[str, Any] = {
            "fromEnteredTime": start_iso,
            "toEnteredTime": end_iso,
        }
        if max_results > 0:
            params["maxResults"] = max(1, min(int(max_results), 3000))
        return self.get_json(url, params)

    def fetch_transactions(self, account_hash: str, start_iso: str, end_iso: str) -> Any:
        url = f"{TRADER_V1}/accounts/{account_hash}/transactions"
        params = {
            "startDate": start_iso,
            "endDate": end_iso,
        }
        return self.get_json(url, params)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Schwab raw orders/transactions JSON into OneJournal ODFS folders.")
    parser.add_argument("--start", required=True, type=_parse_ymd, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, type=_parse_ymd, help="End date YYYY-MM-DD.")
    parser.add_argument("--fetch-date", default=datetime.now().date().isoformat(), help="Raw snapshot folder date, default today.")
    parser.add_argument("--token-path", default=str(DEFAULT_TOKEN_PATH), help="Schwab token JSON path.")
    parser.add_argument("--account-hash", default="", help="Optional Schwab account hash. If omitted, fetch accountNumbers first.")
    parser.add_argument("--account-index", type=int, default=0, help="Account index if account hash omitted. Default 0.")
    parser.add_argument("--max-results", type=int, default=3000, help="Orders maxResults, capped at 3000.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing raw files for this window.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only. No network. No files written.")
    args = parser.parse_args()

    if args.end < args.start:
        raise SystemExit("FAIL: --end must be >= --start")

    client_id = os.environ.get("CLIENT_ID", "").strip()
    client_secret = os.environ.get("CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("REDIRECT_URI", "https://127.0.0.1:8182/callback").strip()

    start_iso = utc_day_start(args.start)
    end_iso = utc_day_end(args.end)
    fetch_date = _parse_ymd(args.fetch_date).isoformat()

    print("===== Schwab raw history fetch =====")
    print(f"PROJECT_DIR       : {PROJECT_DIR}")
    print(f"MODE              : read-only raw fetch")
    print(f"BROKER_API        : GET only")
    print(f"ORDER_WRITE       : disabled")
    print(f"DUCKDB_WRITE      : disabled")
    print(f"NORMALIZE_CSV     : disabled")
    print(f"SCHWAB_BASE       : {SCHWAB_BASE}")
    print(f"TOKEN_PATH        : {Path(args.token_path).expanduser()}")
    print(f"START             : {args.start.isoformat()}")
    print(f"END               : {args.end.isoformat()}")
    print(f"START_ISO         : {start_iso}")
    print(f"END_ISO           : {end_iso}")
    print(f"FETCH_DATE        : {fetch_date}")
    print(f"DRY_RUN           : {args.dry_run}")

    if args.dry_run:
        print("")
        print("===== Result =====")
        print("STATUS            : OK")
        print("ACTION            : dry-run only; no network calls and no files written")
        return 0

    if not client_id:
        raise SystemExit("FAIL: CLIENT_ID environment variable is required")

    auth = SchwabAuth(
        store=TokenStore(Path(args.token_path).expanduser()),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    client = SchwabReadOnlyClient(auth=auth, session=requests.Session())

    if args.account_hash:
        account_hash = args.account_hash.strip()
        print(f"ACCOUNT_HASH      : {account_hash}")
    else:
        accounts = client.account_numbers()
        if args.account_index < 0 or args.account_index >= len(accounts):
            raise SystemExit(f"FAIL: account-index {args.account_index} out of range; accounts={len(accounts)}")
        account_hash = accounts[args.account_index]["hashValue"]
        print(f"ACCOUNTS_FOUND    : {len(accounts)}")
        print(f"ACCOUNT_INDEX     : {args.account_index}")
        print(f"ACCOUNT_HASH      : {account_hash}")

    orders = client.fetch_orders(account_hash, start_iso, end_iso, args.max_results)
    transactions = client.fetch_transactions(account_hash, start_iso, end_iso)

    orders_path = RAW_ROOT / fetch_date / "orders_all" / f"{account_hash}__{args.start.isoformat()}__{args.end.isoformat()}.json"
    txns_path = RAW_ROOT / fetch_date / "transactions" / f"{account_hash}__{args.start.isoformat()}__{args.end.isoformat()}.json"

    safe_json_write(orders_path, orders, overwrite=args.overwrite)
    safe_json_write(txns_path, transactions, overwrite=args.overwrite)

    orders_count = len(orders) if isinstance(orders, list) else len(orders.get("orders", [])) if isinstance(orders, dict) else 0
    txns_count = len(transactions) if isinstance(transactions, list) else 0

    print("")
    print("===== Saved raw JSON =====")
    print(f"ORDERS_PATH       : {orders_path.relative_to(PROJECT_DIR)}")
    print(f"TRANSACTIONS_PATH : {txns_path.relative_to(PROJECT_DIR)}")
    print(f"ORDERS_COUNT      : {orders_count}")
    print(f"TRANSACTIONS_COUNT: {txns_count}")

    print("")
    print("===== Result =====")
    print("STATUS            : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
