"""Pure diagnostic review of recovered Schwab trade versions.

This is not acquisition validation or canonical import authority. It never
renames a fill, chooses a conflicting version, maps an alias, or persists data.
Callers must verify raw bytes and private account binding before normalization.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Mapping

from onejournal.brokers.schwab.transactions_json import NORMALIZED_FILL_COLUMNS


class ArchiveReviewError(ValueError):
    """A diagnostic input cannot be reviewed safely; messages contain no data."""


@dataclass(frozen=True)
class ArchiveTradeObservation:
    activity_id: str
    raw_sha256: str
    record_sha256: str
    rows: tuple[Mapping[str, str], ...]
    adapter_exclusions: bool = False


@dataclass(frozen=True)
class ArchiveActivityReview:
    activity_fingerprint: str
    source_raw_sha256s: tuple[str, ...]
    source_record_sha256s: tuple[str, ...]
    status: str
    reasons: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    new_rows: tuple[Mapping[str, str], ...]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _checked_row(row: Mapping[str, str], account: str) -> dict[str, str]:
    if (set(row) != set(NORMALIZED_FILL_COLUMNS)
            or any(not isinstance(value, str) for value in row.values())
            or row.get("source_broker") != "schwab"
            or row.get("source_account_id") != account
            or not row.get("source_fill_id")):
        raise ArchiveReviewError("normalized archive row has invalid fields or scope")
    return dict(row)


def review_archive_trade_versions(
    observations: tuple[ArchiveTradeObservation, ...],
    *,
    source_account_id: str,
    existing_rows: tuple[Mapping[str, str], ...] = (),
) -> tuple[ArchiveActivityReview, ...]:
    """Return candidates only when every retained version agrees exactly.

    Version comparison is insensitive to row ordering, but preserves item
    multiplicity. Changed generated IDs are withheld even when economics agree.
    Existing source IDs are retained and must match every normalized field.
    A candidate is suitable only for further diagnostic rehearsal, not import.
    """
    if not isinstance(source_account_id, str) or not source_account_id.strip():
        raise ArchiveReviewError("explicit account scope is required")
    existing = {}
    existing_activities = defaultdict(list)
    for original in existing_rows:
        row = _checked_row(original, source_account_id)
        uid = row["source_fill_id"]
        if uid in existing:
            raise ArchiveReviewError("existing evidence contains duplicate fill IDs")
        match = re.match(r"schwab_txn:([0-9]+):order:", uid)
        if match is None:
            raise ArchiveReviewError("existing fill lacks provider activity identity")
        existing[uid] = row
        existing_activities[match.group(1)].append(row)
    by_activity = defaultdict(list)
    for observation in observations:
        if (not isinstance(observation.activity_id, str)
                or not re.fullmatch(r"[0-9]+", observation.activity_id)
                or type(observation.adapter_exclusions) is not bool
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in (observation.raw_sha256, observation.record_sha256))):
            raise ArchiveReviewError("archive observation lacks exact identity or lineage")
        checked = [_checked_row(row, source_account_id) for row in observation.rows]
        if any(not row["source_fill_id"].startswith(
                f"schwab_txn:{observation.activity_id}:order:") for row in checked):
            raise ArchiveReviewError("archive fill differs from provider activity identity")
        by_activity[observation.activity_id].append((observation, checked))
    results = []
    for activity_id, versions in sorted(by_activity.items()):
        reasons = set()
        signatures = set()
        economic_signatures = set()
        for observation, rows in versions:
            if observation.adapter_exclusions or not rows:
                reasons.add("adapter_exclusions_or_no_trade_rows")
            if len({row["source_fill_id"] for row in rows}) != len(rows):
                reasons.add("duplicate_fill_id_within_activity")
            signatures.add(_json(sorted(rows, key=_json)))
            economic_signatures.add(_json(sorted(
                ({key: value for key, value in row.items() if key != "source_fill_id"}
                 for row in rows), key=_json)))
            for row in rows:
                old = existing.get(row["source_fill_id"])
                if old is not None and old != row:
                    reasons.add("existing_fill_content_conflict")
        if len(signatures) > 1:
            reasons.add("generated_fill_identity_changed" if len(economic_signatures) == 1
                        else "normalized_version_conflict")
        current_activity = existing_activities.get(activity_id)
        if current_activity is not None:
            current_signature = _json(sorted(current_activity, key=_json))
            if signatures != {current_signature}:
                current_economics = _json(sorted(
                    ({key: value for key, value in row.items() if key != "source_fill_id"}
                     for row in current_activity), key=_json))
                reasons.add("existing_activity_identity_changed"
                            if economic_signatures == {current_economics}
                            else "existing_activity_content_conflict")
        # Only equivalent versions may yield rows. No preferred source version
        # is chosen, and conflicts yield no rows at all for this activity.
        rows = () if reasons else tuple(MappingProxyType(row) for row in
                                        sorted(versions[0][1], key=_json))
        new_rows = tuple(row for row in rows if row["source_fill_id"] not in existing)
        results.append(ArchiveActivityReview(
            activity_fingerprint=sha256(_json([source_account_id, activity_id]).encode()).hexdigest(),
            source_raw_sha256s=tuple(sorted({item.raw_sha256 for item, _ in versions})),
            source_record_sha256s=tuple(sorted({item.record_sha256 for item, _ in versions})),
            status="withheld" if reasons else "candidate" if new_rows else "existing_replay",
            reasons=tuple(sorted(reasons)), rows=rows, new_rows=new_rows,
        ))
    return tuple(results)
