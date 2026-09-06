"""Deterministic Phase 1 Schwab evidence-to-journal materialization.

This module has no provider or filesystem discovery capability. It consumes one
already validated and persisted evidence assembly, writes canonical fills, and
derives conservative journal episodes. A scope whose first captured close needs
earlier history remains visible as review-required and receives no financial
aggregate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import duckdb

from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.episodes import TradeEpisodePreview, build_episode_previews_from_fills
from onejournal.journal.lifecycle import LifecycleContractError, build_lifecycle_fill_events
from onejournal.journal.schwab_evidence_assembly import (
    SchwabPhase1EvidenceAssembly,
    canonical_schwab_evidence_json,
    validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_import_repository import (
    load_schwab_phase1_evidence_assembly,
)
from onejournal.pnl.calculations import build_instrument_key


MATERIALIZATION_CONTRACT_VERSION = "onejournal.phase1-journal-materialization.v1"
MIGRATION_VERSION = "0018"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0018_add_phase1_journal_materialization.sql"
)
REQUIRED_TABLES = {
    "phase1_journal_materialization_runs",
    "phase1_journal_materialized_fills",
    "phase1_journal_materialized_episodes",
    "phase1_journal_materialized_episode_fills",
}


@dataclass(frozen=True)
class MaterializedEpisode:
    preview: TradeEpisodePreview
    scope_uid: str
    lifecycle_quality: str
    reason_code: str | None
    fill_uids: tuple[str, ...]
    episode_fingerprint: str


@dataclass(frozen=True)
class SchwabJournalMaterializationPlan:
    materialization_uid: str
    result_fingerprint: str
    fills: tuple[NormalizedFill, ...]
    source_record_fingerprints: tuple[tuple[str, str], ...]
    episodes: tuple[MaterializedEpisode, ...]
    lifecycle_resolved_scope_count: int
    review_required_scope_count: int
    lifecycle_resolved_fill_count: int
    review_required_fill_count: int
    final_status: str


@dataclass(frozen=True)
class SchwabJournalMaterializationResult:
    materialization_uid: str
    fill_count: int
    episode_count: int
    lifecycle_resolved_scope_count: int
    review_required_scope_count: int
    lifecycle_resolved_fill_count: int
    review_required_fill_count: int
    final_status: str
    created: bool
    replayed: bool


def _digest(value: object) -> str:
    return sha256(canonical_schwab_evidence_json(value).encode("utf-8")).hexdigest()


def _text(record: Mapping[str, Any], field: str, *, optional: bool = False) -> str | None:
    value = record.get(field)
    normalized = "" if value is None else str(value).strip()
    if not normalized:
        if optional:
            return None
        raise ValueError(f"fill record lacks {field}")
    return normalized


def _decimal(record: Mapping[str, Any], field: str, *, optional: bool = False) -> Decimal | None:
    value = _text(record, field, optional=optional)
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"fill record {field} must be decimal") from exc
    if not result.is_finite():
        raise ValueError(f"fill record {field} must be finite")
    return result


def _date(record: Mapping[str, Any], field: str, *, optional: bool = False) -> date | None:
    value = _text(record, field, optional=optional)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"fill record {field} must be an ISO date") from exc


def _instant(record: Mapping[str, Any], field: str) -> datetime:
    value = _text(record, field)
    assert value is not None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"fill record {field} must be an ISO datetime") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"fill record {field} must include a timezone")
    return result.astimezone(UTC)


def _normalized_fill(
    record: Mapping[str, Any],
    *,
    assembly: SchwabPhase1EvidenceAssembly,
    raw_locator: str,
) -> NormalizedFill:
    source_broker = _text(record, "source_broker")
    source_account_id = _text(record, "source_account_id")
    source_fill_id = _text(record, "source_fill_id")
    if source_broker != assembly.provider or source_account_id != assembly.source_account_id:
        raise ValueError("fill scope differs from evidence assembly")
    asof = _date(record, "asof")
    assert asof is not None
    if not assembly.lifecycle_window_start <= asof <= assembly.lifecycle_window_end:
        raise ValueError("fill asof is outside the accepted lifecycle window")
    quantity = _decimal(record, "quantity")
    if quantity is None or quantity <= 0:
        raise ValueError("fill quantity must be positive")
    return NormalizedFill(
        fill_uid=f"{source_broker}:{source_account_id}:{source_fill_id}",
        source_broker=source_broker,
        source_account_id=source_account_id,
        source_fill_id=source_fill_id,
        source_order_id=_text(record, "source_order_id", optional=True),
        episode_group_id=_text(record, "episode_group_id", optional=True),
        asof=asof,
        filled_at=_instant(record, "filled_at"),
        asset_class=_text(record, "asset_class"),
        symbol=_text(record, "symbol"),
        side=_text(record, "side").upper(),
        quantity=quantity,
        fill_price=_decimal(record, "fill_price"),
        commission=_decimal(record, "commission"),
        fees=_decimal(record, "fees"),
        currency=_text(record, "currency").upper(),
        fetched_at=assembly.assembled_at_utc.astimezone(UTC),
        raw_path=raw_locator,
        option_symbol=_text(record, "option_symbol", optional=True),
        underlying_symbol=_text(record, "underlying_symbol", optional=True),
        option_type=_text(record, "option_type", optional=True),
        expiry=_date(record, "expiry", optional=True),
        strike=_decimal(record, "strike", optional=True),
        multiplier=_decimal(record, "multiplier", optional=True),
        open_close=_text(record, "open_close", optional=True),
        execution_venue=_text(record, "execution_venue", optional=True),
        liquidity_flag=_text(record, "liquidity_flag", optional=True),
    )


def _scope_key(fill: NormalizedFill) -> tuple[str, str, str, str, str]:
    episode_key = (fill.episode_group_id or "").strip() or build_instrument_key(fill)
    return (
        fill.source_broker,
        fill.source_account_id,
        fill.asset_class,
        fill.currency.upper(),
        episode_key,
    )


def _primary_symbol(fills: list[NormalizedFill]) -> str:
    values = sorted(
        {
            (fill.underlying_symbol or fill.symbol).strip().upper()
            for fill in fills
            if (fill.underlying_symbol or fill.symbol).strip()
        }
    )
    if len(values) != 1:
        raise ValueError("review-required lifecycle scope has ambiguous primary symbol")
    return values[0]


def _leg(fill: NormalizedFill) -> dict[str, Any]:
    return {
        "fill_uid": fill.fill_uid,
        "asset_class": fill.asset_class,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": format(fill.quantity, "f"),
        "fill_price": format(fill.fill_price, "f"),
        "commission": format(fill.commission, "f"),
        "fees": format(fill.fees, "f"),
        "option_symbol": fill.option_symbol,
        "underlying_symbol": fill.underlying_symbol,
        "option_type": fill.option_type,
        "expiry": fill.expiry.isoformat() if fill.expiry else None,
        "strike": format(fill.strike, "f") if fill.strike is not None else None,
        "multiplier": format(fill.multiplier, "f") if fill.multiplier is not None else None,
    }


def _episode(
    preview: TradeEpisodePreview,
    *,
    scope_uid: str,
    quality: str,
    reason: str | None,
) -> MaterializedEpisode:
    fill_uids = tuple(str(leg["fill_uid"]) for leg in preview.legs)
    public_episode_uid = f"trade-episode:{_digest((scope_uid, preview.episode_uid, fill_uids))}"
    preview = replace(preview, episode_uid=public_episode_uid)
    payload = {
        "preview": asdict(preview),
        "scope_uid": scope_uid,
        "lifecycle_quality": quality,
        "reason_code": reason,
        "fill_uids": fill_uids,
    }
    return MaterializedEpisode(
        preview=preview,
        scope_uid=scope_uid,
        lifecycle_quality=quality,
        reason_code=reason,
        fill_uids=fill_uids,
        episode_fingerprint=_digest(payload),
    )


def build_schwab_journal_materialization_plan(
    assembly: SchwabPhase1EvidenceAssembly,
) -> SchwabJournalMaterializationPlan:
    """Build a deterministic plan without opening a database."""

    validate_schwab_phase1_evidence_assembly(assembly)
    fill_family = next(family for family in assembly.families if family.family == "fills")
    raw_locator = (
        f"phase1-evidence:{assembly.result_fingerprint}:fills:"
        f"{fill_family.family_fingerprint}"
    )
    fills = tuple(
        _normalized_fill(record, assembly=assembly, raw_locator=raw_locator)
        for record in fill_family.records
    )
    if len({fill.fill_uid for fill in fills}) != len(fills):
        raise ValueError("materialization contains duplicate fill identities")
    source_fingerprints = tuple(
        sorted(
            (fill.fill_uid, _digest(record))
            for fill, record in zip(fills, fill_family.records, strict=True)
        )
    )

    grouped: dict[tuple[str, str, str, str, str], list[NormalizedFill]] = defaultdict(list)
    for fill in fills:
        grouped[_scope_key(fill)].append(fill)

    episodes: list[MaterializedEpisode] = []
    resolved_scopes = review_scopes = resolved_fills = review_fills = 0
    for scope_key in sorted(grouped):
        scope_fills = grouped[scope_key]
        scope_uid = f"journal-scope:{_digest(scope_key)}"
        try:
            build_lifecycle_fill_events(scope_fills)
        except LifecycleContractError as exc:
            if not str(exc).startswith("Unmatched close quantity"):
                raise ValueError("unsupported lifecycle evidence in materialization") from exc
            review_scopes += 1
            review_fills += len(scope_fills)
            ordered = sorted(scope_fills, key=lambda item: (item.filled_at, item.fill_uid))
            preview = TradeEpisodePreview(
                episode_uid="review-required",
                source_account_id=assembly.source_account_id,
                primary_symbol=_primary_symbol(ordered),
                asset_class=ordered[0].asset_class,
                opened_at=ordered[0].filled_at,
                status="review_required",
                fill_count=len(ordered),
                net_quantity=Decimal("0"),
                gross_cashflow=Decimal("0"),
                total_commission=Decimal("0"),
                total_fees=Decimal("0"),
                source_broker=assembly.provider,
                strategy_type="unknown",
                strategy_label="Lifecycle Review Required",
                leg_count=len(ordered),
                leg_summary="Financial aggregates withheld pending earlier history",
                cashflow_label="unavailable",
                legs=[_leg(fill) for fill in ordered],
            )
            episodes.append(
                _episode(
                    preview,
                    scope_uid=scope_uid,
                    quality="review_required",
                    reason="history_extension_required",
                )
            )
            continue

        resolved_scopes += 1
        resolved_fills += len(scope_fills)
        for preview in build_episode_previews_from_fills(scope_fills):
            episodes.append(
                _episode(
                    preview,
                    scope_uid=scope_uid,
                    quality="resolved",
                    reason=None,
                )
            )

    episodes.sort(key=lambda item: item.preview.episode_uid)
    if sorted(fill.fill_uid for fill in fills) != sorted(
        fill_uid for episode in episodes for fill_uid in episode.fill_uids
    ):
        raise ValueError("every materialized fill must belong to exactly one episode")
    final_status = (
        "ready"
        if assembly.final_status == "ready" and review_scopes == 0
        else "review_required"
    )
    result_payload = {
        "contract_version": MATERIALIZATION_CONTRACT_VERSION,
        "assembly_uid": assembly.assembly_uid,
        "assembly_fingerprint": assembly.result_fingerprint,
        "fills": source_fingerprints,
        "episodes": tuple(
            (episode.preview.episode_uid, episode.episode_fingerprint)
            for episode in episodes
        ),
        "lifecycle_resolved_scope_count": resolved_scopes,
        "review_required_scope_count": review_scopes,
        "lifecycle_resolved_fill_count": resolved_fills,
        "review_required_fill_count": review_fills,
        "final_status": final_status,
    }
    fingerprint = _digest(result_payload)
    return SchwabJournalMaterializationPlan(
        materialization_uid=f"schwab-phase1-journal-materialization:{fingerprint}",
        result_fingerprint=fingerprint,
        fills=fills,
        source_record_fingerprints=source_fingerprints,
        episodes=tuple(episodes),
        lifecycle_resolved_scope_count=resolved_scopes,
        review_required_scope_count=review_scopes,
        lifecycle_resolved_fill_count=resolved_fills,
        review_required_fill_count=review_fills,
        final_status=final_status,
    )


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("financial instant must include a timezone")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fill_db_row(
    fill: NormalizedFill,
    *,
    import_run_id: str,
) -> tuple[Any, ...]:
    return (
        fill.fill_uid, fill.source_broker, fill.source_account_id,
        fill.source_fill_id, fill.source_order_id, fill.episode_group_id,
        fill.asof, _utc_naive(fill.filled_at), fill.asset_class,
        fill.symbol, fill.side, fill.quantity, fill.fill_price,
        fill.commission, fill.fees, fill.currency,
        _utc_naive(fill.fetched_at), fill.raw_path, fill.option_symbol,
        fill.underlying_symbol, fill.option_type, fill.expiry,
        fill.strike, fill.multiplier, fill.open_close,
        fill.execution_venue, fill.liquidity_flag, import_run_id,
        _utc_text(fill.filled_at), _utc_text(fill.fetched_at),
    )


def _episode_db_row(
    item: MaterializedEpisode,
    *,
    updated_at: datetime,
) -> tuple[Any, ...]:
    return (
        item.preview.episode_uid, item.preview.source_broker,
        item.preview.source_account_id, item.preview.primary_symbol,
        item.preview.asset_class, item.preview.strategy_type,
        item.preview.strategy_label, _utc_naive(item.preview.opened_at),
        item.preview.status, item.preview.fill_count,
        item.preview.leg_count, item.preview.leg_summary,
        item.preview.cashflow_label,
        None if item.lifecycle_quality == "review_required" else item.preview.net_quantity,
        None if item.lifecycle_quality == "review_required" else item.preview.gross_cashflow,
        None if item.lifecycle_quality == "review_required" else item.preview.total_commission,
        None if item.lifecycle_quality == "review_required" else item.preview.total_fees,
        updated_at,
    )


def _leg_db_rows(plan: SchwabJournalMaterializationPlan) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in plan.episodes:
        for index, leg in enumerate(item.preview.legs, start=1):
            rows.append(
                (
                    item.preview.episode_uid, index, leg.get("asset_class"),
                    leg.get("symbol"), leg.get("side"),
                    Decimal(str(leg["quantity"])) if leg.get("quantity") is not None else None,
                    leg.get("option_type"),
                    date.fromisoformat(str(leg["expiry"])) if leg.get("expiry") else None,
                    Decimal(str(leg["strike"])) if leg.get("strike") is not None else None,
                    json.dumps(leg, sort_keys=True, separators=(",", ":")),
                )
            )
    return rows


def _database_contract(con: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError("database is missing migration 0018 table(s): " + ", ".join(sorted(missing)))
    row = con.execute(
        "SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version = ?",
        [MIGRATION_VERSION],
    ).fetchone()
    expected = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    if row != ("add_phase1_journal_materialization", expected, "applied"):
        raise ValueError("database migration 0018 ledger does not match repository")


def _result(plan: SchwabJournalMaterializationPlan, *, created: bool) -> SchwabJournalMaterializationResult:
    return SchwabJournalMaterializationResult(
        materialization_uid=plan.materialization_uid,
        fill_count=len(plan.fills),
        episode_count=len(plan.episodes),
        lifecycle_resolved_scope_count=plan.lifecycle_resolved_scope_count,
        review_required_scope_count=plan.review_required_scope_count,
        lifecycle_resolved_fill_count=plan.lifecycle_resolved_fill_count,
        review_required_fill_count=plan.review_required_fill_count,
        final_status=plan.final_status,
        created=created,
        replayed=not created,
    )


def _verify_replay(
    con: duckdb.DuckDBPyConnection,
    assembly: SchwabPhase1EvidenceAssembly,
    plan: SchwabJournalMaterializationPlan,
) -> None:
    run = con.execute(
        """
        SELECT contract_version, assembly_uid, source_account_id, asof_date,
               fill_count, episode_count, lifecycle_resolved_scope_count,
               review_required_scope_count, lifecycle_resolved_fill_count,
               review_required_fill_count, final_status, result_fingerprint,
               materialized_at
        FROM phase1_journal_materialization_runs WHERE materialization_uid = ?
        """,
        [plan.materialization_uid],
    ).fetchone()
    expected = (
        MATERIALIZATION_CONTRACT_VERSION,
        assembly.assembly_uid,
        assembly.source_account_id,
        assembly.asof,
        len(plan.fills),
        len(plan.episodes),
        plan.lifecycle_resolved_scope_count,
        plan.review_required_scope_count,
        plan.lifecycle_resolved_fill_count,
        plan.review_required_fill_count,
        plan.final_status,
        plan.result_fingerprint,
        run[12] if run is not None else None,
    )
    if run != expected:
        raise ValueError("materialization identity conflict: stored run differs")
    materialized_at = run[12]
    stored_fills = con.execute(
        """
        SELECT fill_uid, source_record_fingerprint
        FROM phase1_journal_materialized_fills
        WHERE materialization_uid = ? ORDER BY fill_uid
        """,
        [plan.materialization_uid],
    ).fetchall()
    if stored_fills != list(plan.source_record_fingerprints):
        raise ValueError("stored materialized fill lineage differs")
    stored_episodes = con.execute(
        """
        SELECT episode_uid, scope_uid, lifecycle_quality, reason_code,
               source_fill_count, episode_fingerprint
        FROM phase1_journal_materialized_episodes
        WHERE materialization_uid = ? ORDER BY episode_uid
        """,
        [plan.materialization_uid],
    ).fetchall()
    expected_episodes = [
        (
            item.preview.episode_uid,
            item.scope_uid,
            item.lifecycle_quality,
            item.reason_code,
            len(item.fill_uids),
            item.episode_fingerprint,
        )
        for item in plan.episodes
    ]
    if stored_episodes != expected_episodes:
        raise ValueError("stored materialized episode lineage differs")
    linked = con.execute(
        """
        SELECT episode_uid, leg_index, fill_uid
        FROM phase1_journal_materialized_episode_fills
        WHERE materialization_uid = ? ORDER BY episode_uid, leg_index
        """,
        [plan.materialization_uid],
    ).fetchall()
    expected_links = [
        (item.preview.episode_uid, index, fill_uid)
        for item in plan.episodes
        for index, fill_uid in enumerate(item.fill_uids, start=1)
    ]
    if linked != expected_links:
        raise ValueError("stored episode-to-fill lineage differs")
    stored_fill_rows = con.execute(
        """
        SELECT f.fill_uid, f.source_broker, f.source_account_id,
               f.source_fill_id, f.source_order_id, f.episode_group_id,
               f.asof_date, f.filled_at, f.asset_class, f.symbol, f.side,
               f.quantity, f.fill_price, f.commission, f.fees, f.currency,
               f.fetched_at, f.raw_path, f.option_symbol, f.underlying_symbol,
               f.option_type, f.expiry, f.strike, f.multiplier, f.open_close,
               f.execution_venue, f.liquidity_flag, f.import_run_id,
               f.filled_at_utc, f.fetched_at_utc
        FROM phase1_journal_materialized_fills m
        JOIN normalized_fills f ON f.fill_uid = m.fill_uid
        WHERE m.materialization_uid = ? ORDER BY f.fill_uid
        """,
        [plan.materialization_uid],
    ).fetchall()
    expected_fill_rows = sorted(
        (_fill_db_row(fill, import_run_id=plan.materialization_uid) for fill in plan.fills),
        key=lambda row: row[0],
    )
    if stored_fill_rows != expected_fill_rows:
        raise ValueError("stored normalized fills differ from materialization plan")
    stored_episode_rows = con.execute(
        """
        SELECT e.episode_uid, e.source_broker, e.source_account_id,
               e.primary_symbol, e.asset_class, e.strategy_type,
               e.strategy_label, e.opened_at, e.status, e.fill_count,
               e.leg_count, e.leg_summary, e.cashflow_label, e.net_quantity,
               e.gross_cashflow, e.commission, e.fees, e.updated_at
        FROM phase1_journal_materialized_episodes m
        JOIN trade_episodes e ON e.episode_uid = m.episode_uid
        WHERE m.materialization_uid = ? ORDER BY e.episode_uid
        """,
        [plan.materialization_uid],
    ).fetchall()
    expected_episode_rows = [
        _episode_db_row(item, updated_at=materialized_at) for item in plan.episodes
    ]
    if stored_episode_rows != expected_episode_rows:
        raise ValueError("stored trade episodes differ from materialization plan")
    stored_leg_rows = con.execute(
        """
        SELECT l.episode_uid, l.leg_index, l.asset_class, l.symbol, l.side,
               l.quantity, l.option_type, l.expiry, l.strike, l.raw_leg_json
        FROM phase1_journal_materialized_episode_fills m
        JOIN trade_episode_legs l
          ON l.episode_uid = m.episode_uid AND l.leg_index = m.leg_index
        WHERE m.materialization_uid = ? ORDER BY l.episode_uid, l.leg_index
        """,
        [plan.materialization_uid],
    ).fetchall()
    if stored_leg_rows != _leg_db_rows(plan):
        raise ValueError("stored trade episode legs differ from materialization plan")


def persist_schwab_journal_materialization(
    db_path: Path,
    assembly: SchwabPhase1EvidenceAssembly,
    *,
    materialized_at: datetime | None = None,
) -> SchwabJournalMaterializationResult:
    """Atomically materialize one exact persisted assembly or verify its replay."""

    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    stored = load_schwab_phase1_evidence_assembly(db_path, assembly_uid=assembly.assembly_uid)
    if stored.result_fingerprint != assembly.result_fingerprint:
        raise ValueError("database does not contain the exact supplied assembly")
    plan = build_schwab_journal_materialization_plan(assembly)
    timestamp = materialized_at or datetime.now(UTC)
    timestamp_naive = _utc_naive(timestamp)
    con = duckdb.connect(str(db_path))
    began = False
    try:
        _database_contract(con)
        existing = con.execute(
            "SELECT 1 FROM phase1_journal_materialization_runs WHERE materialization_uid = ?",
            [plan.materialization_uid],
        ).fetchone()
        if existing is not None:
            _verify_replay(con, assembly, plan)
            return _result(plan, created=False)
        if con.execute(
            "SELECT COUNT(*) FROM normalized_fills WHERE source_broker = ? AND source_account_id = ?",
            [assembly.provider, assembly.source_account_id],
        ).fetchone()[0]:
            raise ValueError("account already has normalized fills outside this materialization")
        if con.execute(
            "SELECT COUNT(*) FROM trade_episodes WHERE source_broker = ? AND source_account_id = ?",
            [assembly.provider, assembly.source_account_id],
        ).fetchone()[0]:
            raise ValueError("account already has trade episodes outside this materialization")

        con.execute("BEGIN TRANSACTION")
        began = True
        con.execute(
            """
            INSERT INTO import_runs (
                import_run_id, source_type, source_path, asof_date, imported_at,
                row_count, status, notes
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            [
                plan.materialization_uid,
                "schwab_phase1_evidence_assembly",
                assembly.asof,
                timestamp_naive,
                len(plan.fills),
                plan.final_status,
                f"assembly_sha256={assembly.result_fingerprint}; contract={MATERIALIZATION_CONTRACT_VERSION}",
            ],
        )
        con.executemany(
            """
            INSERT INTO normalized_fills (
                fill_uid, source_broker, source_account_id, source_fill_id,
                source_order_id, episode_group_id, asof_date, filled_at,
                asset_class, symbol, side, quantity, fill_price, commission,
                fees, currency, fetched_at, raw_path, option_symbol,
                underlying_symbol, option_type, expiry, strike, multiplier,
                open_close, execution_venue, liquidity_flag, import_run_id,
                filled_at_utc, fetched_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                _fill_db_row(fill, import_run_id=plan.materialization_uid)
                for fill in plan.fills
            ],
        )
        con.executemany(
            """
            INSERT INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol,
                asset_class, strategy_type, strategy_label, opened_at, status,
                fill_count, leg_count, leg_summary, cashflow_label, net_quantity,
                gross_cashflow, commission, fees, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                _episode_db_row(item, updated_at=timestamp_naive)
                for item in plan.episodes
            ],
        )
        leg_rows = _leg_db_rows(plan)
        con.executemany(
            """
            INSERT INTO trade_episode_legs (
                episode_uid, leg_index, asset_class, symbol, side, quantity,
                option_type, expiry, strike, raw_leg_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            leg_rows,
        )
        con.execute(
            """
            INSERT INTO phase1_journal_materialization_runs (
                materialization_uid, contract_version, assembly_uid,
                source_account_id, asof_date, fill_count, episode_count,
                lifecycle_resolved_scope_count, review_required_scope_count,
                lifecycle_resolved_fill_count, review_required_fill_count,
                final_status, result_fingerprint, materialized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                plan.materialization_uid, MATERIALIZATION_CONTRACT_VERSION,
                assembly.assembly_uid, assembly.source_account_id, assembly.asof,
                len(plan.fills), len(plan.episodes),
                plan.lifecycle_resolved_scope_count,
                plan.review_required_scope_count,
                plan.lifecycle_resolved_fill_count,
                plan.review_required_fill_count, plan.final_status,
                plan.result_fingerprint, timestamp_naive,
            ],
        )
        con.executemany(
            """
            INSERT INTO phase1_journal_materialized_fills (
                materialization_uid, fill_uid, source_record_fingerprint
            ) VALUES (?, ?, ?)
            """,
            [
                (plan.materialization_uid, fill_uid, fingerprint)
                for fill_uid, fingerprint in plan.source_record_fingerprints
            ],
        )
        con.executemany(
            """
            INSERT INTO phase1_journal_materialized_episodes (
                materialization_uid, episode_uid, scope_uid, lifecycle_quality,
                reason_code, source_fill_count, episode_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan.materialization_uid, item.preview.episode_uid,
                    item.scope_uid, item.lifecycle_quality, item.reason_code,
                    len(item.fill_uids), item.episode_fingerprint,
                )
                for item in plan.episodes
            ],
        )
        con.executemany(
            """
            INSERT INTO phase1_journal_materialized_episode_fills (
                materialization_uid, episode_uid, leg_index, fill_uid
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (plan.materialization_uid, item.preview.episode_uid, index, fill_uid)
                for item in plan.episodes
                for index, fill_uid in enumerate(item.fill_uids, start=1)
            ],
        )
        con.execute("COMMIT")
        began = False
        _verify_replay(con, assembly, plan)
        return _result(plan, created=True)
    except Exception:
        if began:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def privacy_safe_materialization_audit(
    result: SchwabJournalMaterializationResult,
) -> dict[str, Any]:
    return {
        "contract_version": MATERIALIZATION_CONTRACT_VERSION,
        "materialization_uid": result.materialization_uid,
        "fill_count": result.fill_count,
        "episode_count": result.episode_count,
        "lifecycle_resolved_scope_count": result.lifecycle_resolved_scope_count,
        "review_required_scope_count": result.review_required_scope_count,
        "lifecycle_resolved_fill_count": result.lifecycle_resolved_fill_count,
        "review_required_fill_count": result.review_required_fill_count,
        "final_status": result.final_status,
        "operation": "materialized" if result.created else "replayed",
    }
