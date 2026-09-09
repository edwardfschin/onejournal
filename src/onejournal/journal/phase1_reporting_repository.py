"""Immutable bounded Phase 1 report-release persistence and read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
from typing import Any, Iterable, Literal

import duckdb

from onejournal.journal.broker_current_position_valuation_repository import (
    BrokerCurrentPositionValuationReadBack,
    load_broker_current_position_valuation_run,
)


REPORTING_CONTRACT_VERSION = "onejournal.phase1-report-release.v1"
REPORTING_RELEASE_AUTHORIZATION_VERSION = (
    "onejournal.phase1-report-release-authorization.v1"
)
Quality = Literal["valid", "stale", "incomplete", "reconciliation_pending", "unavailable", "failed"]


class Phase1ReportingError(ValueError):
    """Raised when a report release cannot be safely read or persisted."""


@dataclass(frozen=True)
class ReportingReleaseAuthorization:
    report_release_uid: str
    report_release_fingerprint: str
    owner_acceptance_uid: str


def load_reporting_release_authorization(
    path: str | Path,
) -> ReportingReleaseAuthorization:
    """Load one exact owner-only report authorization at process start."""

    supplied_path = Path(path).expanduser()
    if supplied_path.is_symlink():
        raise Phase1ReportingError("report authorization must not be a symlink")
    resolved_path = supplied_path.resolve()
    if not resolved_path.is_file():
        raise Phase1ReportingError("report authorization file does not exist")
    if stat.S_IMODE(resolved_path.stat().st_mode) != 0o600:
        raise Phase1ReportingError("report authorization file must use mode 0600")
    if stat.S_IMODE(resolved_path.parent.stat().st_mode) != 0o700:
        raise Phase1ReportingError(
            "report authorization directory must use mode 0700"
        )
    try:
        document = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase1ReportingError("report authorization document is invalid") from exc
    required = {
        "contract_version",
        "report_release_uid",
        "report_release_fingerprint",
        "owner_acceptance_uid",
        "decision",
        "accepted_scope",
        "approval_source",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise Phase1ReportingError("report authorization document is invalid")
    if (
        document["contract_version"] != REPORTING_RELEASE_AUTHORIZATION_VERSION
        or document["decision"] != "accepted"
        or document["accepted_scope"] != "bounded_phase1_reporting"
        or document["approval_source"] != "project_owner_explicit_proceed"
        or not isinstance(document["report_release_uid"], str)
        or not document["report_release_uid"]
        or len(document["report_release_uid"]) > 256
        or not isinstance(document["owner_acceptance_uid"], str)
        or not document["owner_acceptance_uid"]
        or len(document["owner_acceptance_uid"]) > 256
        or not isinstance(document["report_release_fingerprint"], str)
        or re.fullmatch(
            r"[0-9a-f]{64}", document["report_release_fingerprint"]
        )
        is None
    ):
        raise Phase1ReportingError("report authorization document is invalid")
    return ReportingReleaseAuthorization(
        report_release_uid=document["report_release_uid"],
        report_release_fingerprint=document["report_release_fingerprint"],
        owner_acceptance_uid=document["owner_acceptance_uid"],
    )


@dataclass(frozen=True)
class ReportingAccount:
    source_broker: str
    source_account_id: str
    account_alias: str


@dataclass(frozen=True)
class RealizedHistoryItem:
    item_uid: str
    source_broker: str
    source_account_id: str
    instrument_key: str
    symbol: str
    asset_class: Literal["equity", "option"]
    close_market_date: date
    closed_at_utc: datetime
    currency: str
    realized_pnl: Decimal
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportingOmission:
    omission_uid: str
    source_broker: str
    source_account_id: str
    close_market_date: date
    symbol: str | None
    reason_code: str
    item_status: Literal["incomplete", "reconciliation_pending", "unavailable"]


@dataclass(frozen=True)
class ReportingRelease:
    report_release_uid: str
    current_valuation_run_uid: str
    current_result_fingerprint: str
    current_owner_acceptance_uid: str
    current_owner_accepted_at_utc: datetime
    realized_calculation_run_id: str
    realized_result_fingerprint: str
    realized_owner_acceptance_uid: str
    realized_owner_accepted_at_utc: datetime
    history_revision_uid: str
    coverage_start_date: date
    coverage_end_date: date
    calculation_version: str
    generated_at_utc: datetime
    release_status: Literal["draft", "owner_accepted"]
    owner_acceptance_uid: str | None
    owner_accepted_at_utc: datetime | None
    accounts: tuple[ReportingAccount, ...]
    items: tuple[RealizedHistoryItem, ...]
    omissions: tuple[ReportingOmission, ...]
    report_release_fingerprint: str


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Phase1ReportingError("timestamps must be UTC instants")
    return value.isoformat().replace("+00:00", "Z")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise Phase1ReportingError("persisted timestamp is not UTC")
    return parsed


def _fingerprint(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise Phase1ReportingError("financial values must be finite decimals")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def calculate_report_release_fingerprint(
    *, release: ReportingRelease, include_fingerprint: bool = False
) -> str:
    payload = {
        "contract_version": REPORTING_CONTRACT_VERSION,
        "report_release_uid": release.report_release_uid,
        "current_valuation_run_uid": release.current_valuation_run_uid,
        "current_result_fingerprint": release.current_result_fingerprint,
        "current_owner_acceptance_uid": release.current_owner_acceptance_uid,
        "current_owner_accepted_at_utc": _utc_text(
            release.current_owner_accepted_at_utc
        ),
        "realized_calculation_run_id": release.realized_calculation_run_id,
        "realized_result_fingerprint": release.realized_result_fingerprint,
        "realized_owner_acceptance_uid": release.realized_owner_acceptance_uid,
        "realized_owner_accepted_at_utc": _utc_text(
            release.realized_owner_accepted_at_utc
        ),
        "history_revision_uid": release.history_revision_uid,
        "coverage_start_date": release.coverage_start_date.isoformat(),
        "coverage_end_date": release.coverage_end_date.isoformat(),
        "calculation_version": release.calculation_version,
        "generated_at_utc": _utc_text(release.generated_at_utc),
        "release_status": release.release_status,
        "owner_acceptance_uid": release.owner_acceptance_uid,
        "owner_accepted_at_utc": _utc_text(release.owner_accepted_at_utc) if release.owner_accepted_at_utc else None,
        "accounts": [a.__dict__ for a in sorted(release.accounts, key=lambda x: (x.source_broker, x.source_account_id))],
        "items": [
            {**x.__dict__, "close_market_date": x.close_market_date.isoformat(), "closed_at_utc": _utc_text(x.closed_at_utc), "realized_pnl": _decimal_text(x.realized_pnl)}
            for x in sorted(release.items, key=lambda x: x.item_uid)
        ],
        "omissions": [
            {
                **x.__dict__,
                "close_market_date": x.close_market_date.isoformat(),
            }
            for x in sorted(release.omissions, key=lambda x: x.omission_uid)
        ],
    }
    if include_fingerprint:
        payload["report_release_fingerprint"] = release.report_release_fingerprint
    return _fingerprint(payload)


def _validate_release(release: ReportingRelease) -> None:
    if release.coverage_start_date > release.coverage_end_date:
        raise Phase1ReportingError("coverage dates are invalid")
    branch_acceptance_uids = (
        release.current_owner_acceptance_uid,
        release.realized_owner_acceptance_uid,
    )
    if any(not value or len(value) > 256 for value in branch_acceptance_uids):
        raise Phase1ReportingError(
            "financial inputs require separate owner acceptance identities"
        )
    _utc_text(release.current_owner_accepted_at_utc)
    _utc_text(release.realized_owner_accepted_at_utc)
    if release.release_status == "owner_accepted":
        if not release.owner_acceptance_uid or not release.owner_accepted_at_utc:
            raise Phase1ReportingError("accepted release requires owner acceptance")
    elif release.owner_acceptance_uid or release.owner_accepted_at_utc:
        raise Phase1ReportingError("draft release cannot carry owner acceptance")
    if any(len(value) != 64 or set(value) - set("0123456789abcdef") for value in (release.current_result_fingerprint, release.realized_result_fingerprint)):
        raise Phase1ReportingError("financial result fingerprints must be SHA-256 hex")
    aliases = [a.account_alias for a in release.accounts]
    if not aliases or len(aliases) != len(set(aliases)) or any(not x or len(x) > 64 for x in aliases):
        raise Phase1ReportingError("account aliases must be present and unique")
    for account in release.accounts:
        normalized_alias = account.account_alias.lower()
        if (account.source_account_id.lower() in normalized_alias
                or re.search(r"\b\d{8,}\b", account.account_alias)
                or re.fullmatch(r"[0-9a-fA-F]{16,}", account.account_alias)):
            raise Phase1ReportingError("account alias is unsafe")
    known = {(x.source_broker, x.source_account_id) for x in release.accounts}
    for item in release.items:
        if (item.source_broker, item.source_account_id) not in known or item.asset_class not in {"equity", "option"}:
            raise Phase1ReportingError("realized item has invalid account or asset scope")
        if not item.symbol or not item.item_uid or not item.instrument_key:
            raise Phase1ReportingError("realized item identity is incomplete")
        _utc_text(item.closed_at_utc)
        decimal_text = _decimal_text(item.realized_pnl)
        integer, _, fraction = decimal_text.lstrip("-").partition(".")
        if len(integer.lstrip("0")) > 11 or len(fraction) > 27:
            raise Phase1ReportingError(
                "realized P&L exceeds DECIMAL(38,27) persistence precision"
            )
        if not release.coverage_start_date <= item.close_market_date <= release.coverage_end_date:
            raise Phase1ReportingError("realized item is outside report coverage")
    if len({x.item_uid for x in release.items}) != len(release.items):
        raise Phase1ReportingError("realized item IDs must be unique")
    if len({x.omission_uid for x in release.omissions}) != len(release.omissions):
        raise Phase1ReportingError("omission IDs must be unique")
    for omission in release.omissions:
        if (omission.source_broker, omission.source_account_id) not in known:
            raise Phase1ReportingError("report omission has invalid account scope")
        if not release.coverage_start_date <= omission.close_market_date <= release.coverage_end_date:
            raise Phase1ReportingError("report omission is outside report coverage")
        if omission.symbol is not None and not omission.symbol:
            raise Phase1ReportingError("report omission symbol is invalid")
    expected = calculate_report_release_fingerprint(release=release)
    if expected != release.report_release_fingerprint:
        raise Phase1ReportingError("report release fingerprint mismatch")


def persist_reporting_release(con: duckdb.DuckDBPyConnection, release: ReportingRelease) -> None:
    _validate_release(release)
    existing = con.execute("SELECT report_release_fingerprint FROM phase1_reporting_releases WHERE report_release_uid = ?", [release.report_release_uid]).fetchone()
    if existing is not None:
        if existing[0] != release.report_release_fingerprint:
            raise Phase1ReportingError("report release UID conflicts with existing immutable state")
        return
    processed = len(release.items) + len(release.omissions)
    available = len(release.items)
    unavailable = sum(x.item_status == "unavailable" for x in release.omissions)
    pending = sum(x.item_status == "reconciliation_pending" for x in release.omissions)
    incomplete = sum(x.item_status == "incomplete" for x in release.omissions)
    reason_counts: dict[str, int] = {}
    for omission in release.omissions:
        reason_counts[omission.reason_code] = reason_counts.get(omission.reason_code, 0) + 1
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """INSERT INTO phase1_reporting_releases (
                   report_release_uid, contract_version,
                   report_release_fingerprint, current_valuation_run_uid,
                   current_result_fingerprint, realized_calculation_run_id,
                   realized_result_fingerprint, history_revision_uid,
                   coverage_start_date, coverage_end_date, calculation_version,
                   generated_at_utc, release_status, owner_acceptance_uid,
                   owner_accepted_at_utc, processed_count, available_count,
                   unavailable_count, reconciliation_pending_count,
                   reason_counts_json, current_owner_acceptance_uid,
                   current_owner_accepted_at_utc,
                   realized_owner_acceptance_uid,
                   realized_owner_accepted_at_utc
               ) VALUES (
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?
               )""",
            [
                release.report_release_uid,
                REPORTING_CONTRACT_VERSION,
                release.report_release_fingerprint,
                release.current_valuation_run_uid,
                release.current_result_fingerprint,
                release.realized_calculation_run_id,
                release.realized_result_fingerprint,
                release.history_revision_uid,
                release.coverage_start_date,
                release.coverage_end_date,
                release.calculation_version,
                _utc_text(release.generated_at_utc),
                release.release_status,
                release.owner_acceptance_uid,
                _utc_text(release.owner_accepted_at_utc)
                if release.owner_accepted_at_utc
                else None,
                processed,
                available,
                unavailable + incomplete,
                pending,
                json.dumps(reason_counts, sort_keys=True),
                release.current_owner_acceptance_uid,
                _utc_text(release.current_owner_accepted_at_utc),
                release.realized_owner_acceptance_uid,
                _utc_text(release.realized_owner_accepted_at_utc),
            ],
        )
        con.executemany("INSERT INTO phase1_reporting_release_accounts VALUES (?, ?, ?, ?)", [(release.report_release_uid, x.source_broker, x.source_account_id, x.account_alias) for x in release.accounts])
        if release.items:
            con.executemany(
                "INSERT INTO phase1_reporting_release_realized_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(release.report_release_uid, x.item_uid, x.source_broker, x.source_account_id, x.instrument_key, x.symbol, x.asset_class, x.close_market_date, _utc_text(x.closed_at_utc), x.currency, _decimal_text(x.realized_pnl), "valid", json.dumps(x.reason_codes)) for x in release.items]
            )
        if release.omissions:
            con.executemany(
                "INSERT INTO phase1_reporting_release_omissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(release.report_release_uid, x.omission_uid, x.source_broker, x.source_account_id, x.close_market_date, x.symbol, x.reason_code, x.item_status) for x in release.omissions]
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def load_reporting_release(con: duckdb.DuckDBPyConnection, *, report_release_uid: str) -> ReportingRelease:
    row = con.execute(
        """SELECT report_release_uid, current_valuation_run_uid,
                  current_result_fingerprint, current_owner_acceptance_uid,
                  current_owner_accepted_at_utc, realized_calculation_run_id,
                  realized_result_fingerprint, realized_owner_acceptance_uid,
                  realized_owner_accepted_at_utc, history_revision_uid,
                  coverage_start_date, coverage_end_date, calculation_version,
                  generated_at_utc, release_status, owner_acceptance_uid,
                  owner_accepted_at_utc, report_release_fingerprint
           FROM phase1_reporting_releases
           WHERE report_release_uid = ?""",
        [report_release_uid],
    ).fetchone()
    if row is None:
        raise Phase1ReportingError("configured report release is unavailable")
    accounts = tuple(ReportingAccount(*x) for x in con.execute("SELECT source_broker, source_account_id, account_alias FROM phase1_reporting_release_accounts WHERE report_release_uid = ? ORDER BY account_alias", [report_release_uid]).fetchall())
    items = tuple(RealizedHistoryItem(x[0], x[1], x[2], x[3], x[4], x[5], x[6], _utc(x[7]), x[8], Decimal(str(x[9])), tuple(json.loads(x[10])) ) for x in con.execute("SELECT item_uid, source_broker, source_account_id, instrument_key, symbol, asset_class, close_market_date, closed_at_utc, currency, realized_pnl, reason_codes_json FROM phase1_reporting_release_realized_items WHERE report_release_uid = ? ORDER BY item_uid", [report_release_uid]).fetchall())
    omissions = tuple(ReportingOmission(*x) for x in con.execute("SELECT omission_uid, source_broker, source_account_id, close_market_date, symbol, reason_code, item_status FROM phase1_reporting_release_omissions WHERE report_release_uid = ? ORDER BY omission_uid", [report_release_uid]).fetchall())
    release = ReportingRelease(
        report_release_uid=row[0],
        current_valuation_run_uid=row[1],
        current_result_fingerprint=row[2],
        current_owner_acceptance_uid=row[3],
        current_owner_accepted_at_utc=_utc(row[4]),
        realized_calculation_run_id=row[5],
        realized_result_fingerprint=row[6],
        realized_owner_acceptance_uid=row[7],
        realized_owner_accepted_at_utc=_utc(row[8]),
        history_revision_uid=row[9],
        coverage_start_date=row[10],
        coverage_end_date=row[11],
        calculation_version=row[12],
        generated_at_utc=_utc(row[13]),
        release_status=row[14],
        owner_acceptance_uid=row[15],
        owner_accepted_at_utc=_utc(row[16]) if row[16] else None,
        accounts=accounts,
        items=items,
        omissions=omissions,
        report_release_fingerprint=row[17],
    )
    _validate_release(release)
    return release


def authorize_reporting_release(release: ReportingRelease, authorization: ReportingReleaseAuthorization) -> None:
    if release.release_status != "owner_accepted":
        raise Phase1ReportingError("report release is not owner accepted")
    if (release.report_release_uid != authorization.report_release_uid
            or release.report_release_fingerprint != authorization.report_release_fingerprint
            or release.owner_acceptance_uid != authorization.owner_acceptance_uid):
        raise Phase1ReportingError("report authorization does not match persisted release")


def selection_fingerprint(release: ReportingRelease, *, action: str, from_date: date | None = None, to_date: date | None = None, account_alias: str | None = None, symbol: str | None = None) -> str:
    return _fingerprint({"release": release.report_release_fingerprint, "action": action, "from": str(from_date) if from_date else None, "to": str(to_date) if to_date else None, "account": account_alias, "symbol": symbol})


def realized_history(release: ReportingRelease, *, from_date: date, to_date: date, account_alias: str | None = None, symbol: str | None = None) -> tuple[Quality, tuple[RealizedHistoryItem, ...], dict[str, int]]:
    if from_date > to_date:
        raise Phase1ReportingError("from date must not be after to date")
    aliases = {x.account_alias: (x.source_broker, x.source_account_id) for x in release.accounts}
    if account_alias is not None and account_alias not in aliases:
        raise Phase1ReportingError("requested account alias is unavailable")
    if from_date < release.coverage_start_date or to_date > release.coverage_end_date:
        return "unavailable", (), {"outside_accepted_coverage": 1}
    if symbol is not None and symbol not in {x.symbol for x in release.items} | {x.symbol for x in release.omissions if x.symbol is not None}:
        raise Phase1ReportingError("requested symbol is unavailable")
    selected = tuple(x for x in release.items if from_date <= x.close_market_date <= to_date and (account_alias is None or (x.source_broker, x.source_account_id) == aliases[account_alias]) and (symbol is None or x.symbol == symbol))
    omissions = [
        x for x in release.omissions
        if from_date <= x.close_market_date <= to_date
        and (account_alias is None or (x.source_broker, x.source_account_id) == aliases[account_alias])
        and (symbol is None or x.symbol is None or x.symbol == symbol)
    ]
    reasons: dict[str, int] = {}
    for item in omissions:
        reasons[item.reason_code] = reasons.get(item.reason_code, 0) + 1
    if any(x.item_status == "reconciliation_pending" for x in omissions):
        return "reconciliation_pending", selected, reasons
    if omissions:
        return "incomplete", selected, reasons
    return "valid", selected, reasons


def current_breakdowns(db_path: Path, release: ReportingRelease) -> tuple[BrokerCurrentPositionValuationReadBack, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    valuation = load_broker_current_position_valuation_run(db_path, valuation_run_uid=release.current_valuation_run_uid)
    if valuation is None:
        raise Phase1ReportingError("current valuation run is unavailable")
    if valuation.result_fingerprint != release.current_result_fingerprint:
        raise Phase1ReportingError("current valuation fingerprint does not match report release")
    aliases = {(x.source_broker, x.source_account_id): x.account_alias for x in release.accounts}
    alias = aliases.get((valuation.source_broker, valuation.source_account_id))
    if alias is None:
        raise Phase1ReportingError("current valuation lacks a private account alias")
    account_groups: dict[str, list[dict[str, Any]]] = {}
    symbol_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in valuation.positions:
        symbol = row["symbol"] if row["asset_class"] == "equity" else row["underlying_symbol"]
        if not symbol:
            raise Phase1ReportingError("current position lacks owner-facing symbol")
        account_groups.setdefault(row["currency"], []).append(row)
        symbol_groups.setdefault((symbol, row["currency"]), []).append(row)
    def summarize(rows: Iterable[dict[str, Any]], *, symbol: str | None) -> dict[str, Any]:
        values = list(rows)
        result: dict[str, Any] = {"account_alias": alias, "symbol": symbol, "currency": values[0]["currency"], "position_count": len(values), "reason_codes": []}
        for metric, status in (("open_cost_basis", "cost_basis_status"), ("broker_market_value", "market_value_status"), ("unrealized_pnl", "unrealized_pnl_status")):
            valid = all(x[status] == "available" and x[metric] is not None for x in values)
            result[metric] = sum((Decimal(str(x[metric])) for x in values), Decimal("0")) if valid else None
            result[f"{metric}_status"] = "valid" if valid else "unavailable"
            if not valid: result["reason_codes"].append(f"{metric}_unavailable")
        return result
    accounts = tuple(
        summarize(rows, symbol=None)
        for _currency, rows in sorted(account_groups.items())
    )
    symbols = tuple(
        summarize(rows, symbol=key[0])
        for key, rows in sorted(symbol_groups.items())
    )
    return valuation, accounts, symbols
