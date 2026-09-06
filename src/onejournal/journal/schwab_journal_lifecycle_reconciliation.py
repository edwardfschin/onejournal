"""Reconcile journal episode state to Schwab terminal events and positions.

This is a pure, credential-free projection.  It never changes source fills or
promotes review-required lifecycle evidence into financial P&L authority.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping

from onejournal.instruments import InstrumentIdentity
from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    SchwabPhase1EvidenceAssembly,
    canonical_schwab_evidence_json,
    validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_materialization import (
    MaterializedEpisode,
    build_schwab_journal_materialization_plan,
)


JOURNAL_LIFECYCLE_RECONCILIATION_VERSION = (
    "onejournal.phase1-journal-lifecycle-reconciliation.v1"
)
_TERMINAL_EVENT_NAMES = {"ASSIGNMENT", "EXERCISE", "EXPIRATION"}


@dataclass(frozen=True)
class JournalEpisodeLifecycleState:
    episode_uid: str
    prior_status: str
    reconciled_status: str
    lifecycle_quality: str
    reason_code: str | None
    position_reconciliation_status: str
    matched_terminal_event_count: int
    state_fingerprint: str


@dataclass(frozen=True)
class SchwabJournalLifecycleReconciliationPlan:
    reconciliation_uid: str
    contract_version: str
    assembly_uid: str
    source_materialization_uid: str
    source_account_id: str
    asof: date
    states: tuple[JournalEpisodeLifecycleState, ...]
    closed_count: int
    open_count: int
    review_required_count: int
    terminal_event_count: int
    terminal_event_leg_count: int
    matched_terminal_event_leg_count: int
    final_status: str
    result_fingerprint: str


def _digest(value: object) -> str:
    return sha256(canonical_schwab_evidence_json(value).encode("utf-8")).hexdigest()


def _family_records(
    assembly: SchwabPhase1EvidenceAssembly, family_name: str
) -> tuple[Mapping[str, Any], ...]:
    return next(
        family.records for family in assembly.families if family.family == family_name
    )


def _decimal(value: object, field: str) -> Decimal:
    if value is None or not str(value).strip():
        raise ValueError(f"{field} is required")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _event_name(record: Mapping[str, Any]) -> str:
    value = str(record.get("event_name") or record.get("event_type") or "").strip()
    return value.split(":", 1)[-1].upper()


def _event_instrument_key(record: Mapping[str, Any], *, currency: str) -> str:
    asset_class = str(record.get("asset_class", "")).strip().lower()
    if asset_class in {"stock", "equity"}:
        return InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency=currency,
            symbol=str(record.get("symbol", "")),
        ).key
    if asset_class != "option":
        raise ValueError("terminal lifecycle leg has an unsupported asset class")
    return InstrumentIdentity(
        asset_class="option",
        market_scope="US",
        currency=currency,
        underlying_symbol=str(
            record.get("underlying_symbol") or record.get("symbol") or ""
        ),
        expiry=date.fromisoformat(str(record.get("expiry", ""))),
        option_right=str(record.get("option_type", "")).upper(),
        strike=_decimal(record.get("strike"), "terminal lifecycle strike"),
        multiplier=_decimal(
            record.get("multiplier"), "terminal lifecycle multiplier"
        ),
    ).key


def _episode_residuals(
    episode: MaterializedEpisode,
    *,
    fills_by_uid: Mapping[str, Any],
) -> dict[str, Decimal]:
    residuals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for fill_uid in episode.fill_uids:
        fill = fills_by_uid[fill_uid]
        side = fill.side.strip().upper()
        if side.startswith("BUY"):
            sign = Decimal("1")
        elif side.startswith("SELL"):
            sign = Decimal("-1")
        else:
            raise ValueError("journal fill has an unsupported side")
        residuals[InstrumentIdentity.from_fill(fill).key] += sign * fill.quantity
    return dict(residuals)


def build_schwab_journal_lifecycle_reconciliation(
    assembly: SchwabPhase1EvidenceAssembly,
) -> SchwabJournalLifecycleReconciliationPlan:
    """Build episode state from fills, terminal events, and one complete snapshot."""

    validate_schwab_phase1_evidence_assembly(assembly)
    if assembly.contract_version != SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2:
        raise ValueError("journal lifecycle reconciliation requires assembly v2")
    account = _family_records(assembly, "account")
    if len(account) != 1 or account[0].get("account_complete") is not True:
        raise ValueError("journal lifecycle reconciliation requires a complete snapshot")
    currency = str(account[0].get("currency", "")).strip().upper()
    if not currency:
        raise ValueError("journal lifecycle reconciliation requires account currency")

    materialization = build_schwab_journal_materialization_plan(assembly)
    fills_by_uid = {fill.fill_uid: fill for fill in materialization.fills}
    episodes_by_uid = {item.preview.episode_uid: item for item in materialization.episodes}
    residuals = {
        uid: _episode_residuals(item, fills_by_uid=fills_by_uid)
        for uid, item in episodes_by_uid.items()
    }

    open_episodes_by_instrument: dict[str, list[str]] = defaultdict(list)
    for item in sorted(
        materialization.episodes,
        key=lambda row: (row.preview.opened_at, row.preview.episode_uid),
    ):
        if item.preview.status != "open":
            continue
        for instrument_key, quantity in residuals[item.preview.episode_uid].items():
            if quantity:
                open_episodes_by_instrument[instrument_key].append(
                    item.preview.episode_uid
                )

    events = _family_records(assembly, "lifecycle_events")
    event_by_uid = {str(record["event_uid"]): record for record in events}
    terminal_events = {
        uid: event
        for uid, event in event_by_uid.items()
        if _event_name(event) in _TERMINAL_EVENT_NAMES
    }
    legs = sorted(
        _family_records(assembly, "lifecycle_event_legs"),
        key=lambda row: (
            str(event_by_uid.get(str(row.get("event_uid")), {}).get("event_at", "")),
            str(row.get("event_uid", "")),
            int(str(row.get("leg_index", "0"))),
        ),
    )
    matched_event_uids: dict[str, set[str]] = defaultdict(set)
    review_event_uids: dict[str, set[str]] = defaultdict(set)
    instrument_event_error: set[str] = set()
    matched_leg_count = 0
    for leg in legs:
        event_uid = str(leg.get("event_uid", ""))
        if event_uid not in terminal_events:
            continue
        if str(leg.get("leg_kind", "")).strip().lower() != "security":
            continue
        if str(leg.get("position_effect", "")).strip().upper() != "CLOSING":
            continue
        instrument_key = _event_instrument_key(leg, currency=currency)
        event_quantity = _decimal(
            leg.get("signed_quantity"), "terminal lifecycle signed_quantity"
        )
        if event_quantity == 0:
            instrument_event_error.add(instrument_key)
            continue
        remaining = event_quantity
        matched_this_leg = False
        for episode_uid in open_episodes_by_instrument.get(instrument_key, []):
            episode_quantity = residuals[episode_uid].get(
                instrument_key, Decimal("0")
            )
            if not episode_quantity or episode_quantity * remaining >= 0:
                continue
            matched = min(abs(episode_quantity), abs(remaining))
            matched_signed = matched if remaining > 0 else -matched
            residuals[episode_uid][instrument_key] = episode_quantity + matched_signed
            remaining -= matched_signed
            matched_event_uids[episode_uid].add(event_uid)
            if str(leg.get("evidence_status", "")).strip().lower() != "observed":
                review_event_uids[episode_uid].add(event_uid)
            matched_this_leg = True
            if remaining == 0:
                break
        if matched_this_leg:
            matched_leg_count += 1
        if remaining != 0:
            instrument_event_error.add(instrument_key)

    positions = {
        str(record["instrument_key"]): _decimal(
            record.get("quantity"), "current position quantity"
        )
        for record in _family_records(assembly, "positions")
    }
    remaining_by_instrument: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in materialization.episodes:
        if item.preview.status != "open":
            continue
        for instrument_key, quantity in residuals[item.preview.episode_uid].items():
            remaining_by_instrument[instrument_key] += quantity

    instrument_matches = {
        key: quantity == positions.get(key, Decimal("0"))
        for key, quantity in remaining_by_instrument.items()
    }
    states: list[JournalEpisodeLifecycleState] = []
    for item in materialization.episodes:
        episode_uid = item.preview.episode_uid
        prior_status = item.preview.status
        episode_residual = residuals[episode_uid]
        keys = tuple(episode_residual)
        if prior_status != "open":
            status = prior_status
            quality = item.lifecycle_quality
            reason = item.reason_code
            position_status = "not_applicable"
        elif any(key in instrument_event_error for key in keys):
            status = "review_required"
            quality = "review_required"
            reason = "terminal_event_quantity_mismatch"
            position_status = "mismatch"
        elif all(quantity == 0 for quantity in episode_residual.values()):
            if any(not instrument_matches.get(key, False) for key in keys):
                status = "review_required"
                quality = "review_required"
                reason = "current_position_quantity_mismatch"
                position_status = "mismatch"
            else:
                status = "closed"
                position_status = "terminal_reconciled"
                if review_event_uids.get(episode_uid):
                    quality = "review_required"
                    reason = "broker_terminal_event_review_required"
                else:
                    quality = "resolved"
                    reason = None
        elif all(instrument_matches.get(key, False) for key in keys):
            status = "open"
            quality = "resolved"
            reason = None
            position_status = "matched_current"
        elif all(positions.get(key, Decimal("0")) == 0 for key in keys):
            status = "review_required"
            quality = "review_required"
            reason = "current_position_absent_closure_evidence_required"
            position_status = "absent_current"
        else:
            status = "review_required"
            quality = "review_required"
            reason = "current_position_quantity_mismatch"
            position_status = "mismatch"
        payload = {
            "episode_uid": episode_uid,
            "prior_status": prior_status,
            "reconciled_status": status,
            "lifecycle_quality": quality,
            "reason_code": reason,
            "position_reconciliation_status": position_status,
            "matched_terminal_event_uids": tuple(
                sorted(matched_event_uids.get(episode_uid, ()))
            ),
        }
        states.append(
            JournalEpisodeLifecycleState(
                episode_uid=episode_uid,
                prior_status=prior_status,
                reconciled_status=status,
                lifecycle_quality=quality,
                reason_code=reason,
                position_reconciliation_status=position_status,
                matched_terminal_event_count=len(
                    matched_event_uids.get(episode_uid, ())
                ),
                state_fingerprint=_digest(payload),
            )
        )

    states.sort(key=lambda state: state.episode_uid)
    closed_count = sum(state.reconciled_status == "closed" for state in states)
    open_count = sum(state.reconciled_status == "open" for state in states)
    review_count = sum(
        state.reconciled_status == "review_required" for state in states
    )
    quality_review_count = sum(
        state.lifecycle_quality == "review_required" for state in states
    )
    payload = {
        "contract_version": JOURNAL_LIFECYCLE_RECONCILIATION_VERSION,
        "assembly_uid": assembly.assembly_uid,
        "source_materialization_uid": materialization.materialization_uid,
        "source_account_id": assembly.source_account_id,
        "asof": assembly.asof,
        "states": tuple(asdict(state) for state in states),
        "terminal_event_count": len(terminal_events),
        "terminal_event_leg_count": len(legs),
        "matched_terminal_event_leg_count": matched_leg_count,
    }
    fingerprint = _digest(payload)
    return SchwabJournalLifecycleReconciliationPlan(
        reconciliation_uid=f"journal-lifecycle-reconciliation:{fingerprint}",
        contract_version=JOURNAL_LIFECYCLE_RECONCILIATION_VERSION,
        assembly_uid=assembly.assembly_uid,
        source_materialization_uid=materialization.materialization_uid,
        source_account_id=assembly.source_account_id,
        asof=assembly.asof,
        states=tuple(states),
        closed_count=closed_count,
        open_count=open_count,
        review_required_count=review_count,
        terminal_event_count=len(terminal_events),
        terminal_event_leg_count=len(legs),
        matched_terminal_event_leg_count=matched_leg_count,
        final_status=(
            "review_required"
            if review_count
            or quality_review_count
            or matched_leg_count
            < sum(
                str(leg.get("event_uid", "")) in terminal_events
                and str(leg.get("leg_kind", "")).strip().lower() == "security"
                and str(leg.get("position_effect", "")).strip().upper()
                == "CLOSING"
                for leg in legs
            )
            else "reconciled"
        ),
        result_fingerprint=fingerprint,
    )


def privacy_safe_lifecycle_reconciliation_audit(
    plan: SchwabJournalLifecycleReconciliationPlan,
) -> dict[str, object]:
    """Return counts and opaque fingerprints without holdings or account data."""

    return {
        "contract_version": plan.contract_version,
        "reconciliation_uid": plan.reconciliation_uid,
        "assembly_uid": plan.assembly_uid,
        "source_materialization_uid": plan.source_materialization_uid,
        "asof": plan.asof.isoformat(),
        "episode_count": len(plan.states),
        "closed_count": plan.closed_count,
        "open_count": plan.open_count,
        "review_required_count": plan.review_required_count,
        "lifecycle_quality_review_required_count": sum(
            state.lifecycle_quality == "review_required" for state in plan.states
        ),
        "terminal_event_count": plan.terminal_event_count,
        "terminal_event_leg_count": plan.terminal_event_leg_count,
        "matched_terminal_event_leg_count": plan.matched_terminal_event_leg_count,
        "final_status": plan.final_status,
        "result_fingerprint": plan.result_fingerprint,
    }
