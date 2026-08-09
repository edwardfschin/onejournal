"""Durable single-owner journal domain services.

All functions operate on an existing DuckDB connection. They never call broker
APIs, write generated payloads, or enable order execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
import re
from typing import Any
from uuid import UUID, uuid4

import duckdb


REVIEW_STATUSES = frozenset({"unreviewed", "needs_review", "mistake_review", "reviewed"})
SETUP_QUALITIES = frozenset({"unknown", "good", "acceptable", "poor", "mistake"})
REVIEW_SOURCES = frozenset({"legacy_backfill", "streamlit", "import", "api"})
ENTRY_SOURCES = frozenset({"streamlit", "import", "operator", "api"})
ENTRY_TYPES = frozenset(
    {
        "pre_trade_plan",
        "entry_thesis",
        "execution_review",
        "exit_review",
        "post_trade_reflection",
        "weekly_review",
        "monthly_review",
        "mistake",
        "lesson",
        "note",
    }
)
ENTRY_STATUSES = frozenset({"active", "archived"})
TAG_TYPES = frozenset({"general", "mistake", "lesson"})
TAG_ACTIONS = frozenset({"assign", "remove"})


class JournalValidationError(ValueError):
    """Raised when journal input violates the approved domain contract."""


class JournalIntegrityError(RuntimeError):
    """Raised when persisted journal history is ambiguous or inconsistent."""


class JournalPolicyError(PermissionError):
    """Raised when a not-yet-approved journal capability is requested."""


@dataclass(frozen=True)
class ReviewWriteResult:
    review_uid: str | None
    history_written: bool
    compatibility_only: bool
    unchanged: bool


@dataclass(frozen=True)
class EntryRevision:
    entry_uid: str
    revision_no: int
    episode_uid: str | None
    entry_type: str
    strategy_uid: str | None
    title: str | None
    body: str
    occurred_at: datetime | None
    entry_status: str
    change_reason: str | None
    created_at: datetime


def utc_now_naive() -> datetime:
    """Return the project database timestamp convention: UTC, timezone-naive."""

    return datetime.now(UTC).replace(tzinfo=None)


def normalize_catalog_name(value: str) -> str:
    """Build the case/whitespace-insensitive catalog uniqueness key."""

    display = _required_text(value, "name")
    return " ".join(display.casefold().split())


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        ).fetchone()[0]
    )


def save_review(
    con: duckdb.DuckDBPyConnection,
    *,
    episode_uid: str,
    review_status: str,
    setup_quality: str,
    entry_reason: str = "",
    notes: str = "",
    source: str,
    created_at: datetime | None = None,
    skip_if_unchanged: bool = False,
    manage_transaction: bool = True,
) -> ReviewWriteResult:
    """Append one review event and update the legacy projection atomically.

    Before migration 0005 is applied, the function preserves the existing
    prototype by writing `manual_reviews` only and reports compatibility-only
    mode. This transitional path prevents a code deploy from breaking the
    current local Streamlit review editor before live migration approval.
    """

    episode_uid = _required_text(episode_uid, "episode_uid")
    _enum(review_status, REVIEW_STATUSES, "review_status")
    _enum(setup_quality, SETUP_QUALITIES, "setup_quality")
    _enum(source, REVIEW_SOURCES, "source")
    created_at = _timestamp(created_at)

    if manage_transaction:
        con.execute("BEGIN TRANSACTION")
    try:
        _require_episode(con, episode_uid)
        current_projection = con.execute(
            """
            SELECT review_status, setup_quality, COALESCE(entry_reason, ''), COALESCE(notes, '')
            FROM manual_reviews WHERE episode_uid = ?
            """,
            [episode_uid],
        ).fetchone()
        incoming = (review_status, setup_quality, entry_reason or "", notes or "")
        if skip_if_unchanged and current_projection == incoming:
            result = ReviewWriteResult(
                review_uid=None,
                history_written=False,
                compatibility_only=not table_exists(con, "journal_reviews"),
                unchanged=True,
            )
            if manage_transaction:
                con.execute("COMMIT")
            return result

        history_available = table_exists(con, "journal_reviews")
        review_uid: str | None = None
        if history_available:
            head_uid = _current_review_head(con, episode_uid)
            review_uid = str(uuid4())
            con.execute(
                """
                INSERT INTO journal_reviews (
                    review_uid, episode_uid, review_status, setup_quality,
                    entry_reason, notes, supersedes_review_uid, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    review_uid,
                    episode_uid,
                    review_status,
                    setup_quality,
                    entry_reason or "",
                    notes or "",
                    head_uid,
                    source,
                    created_at,
                ],
            )

        con.execute(
            """
            INSERT OR REPLACE INTO manual_reviews (
                episode_uid, review_status, setup_quality, entry_reason, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [episode_uid, review_status, setup_quality, entry_reason or "", notes or "", created_at],
        )
        if manage_transaction:
            con.execute("COMMIT")
        return ReviewWriteResult(
            review_uid=review_uid,
            history_written=history_available,
            compatibility_only=not history_available,
            unchanged=False,
        )
    except Exception:
        if manage_transaction:
            con.execute("ROLLBACK")
        raise


def create_entry(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_type: str,
    body: str,
    created_source: str,
    episode_uid: str | None = None,
    strategy_uid: str | None = None,
    title: str | None = None,
    occurred_at: datetime | None = None,
    change_reason: str | None = "initial revision",
    created_at: datetime | None = None,
    entry_uid: str | None = None,
    manage_transaction: bool = True,
) -> EntryRevision:
    """Create one logical entry and immutable revision 1."""

    _enum(entry_type, ENTRY_TYPES, "entry_type")
    _enum(created_source, ENTRY_SOURCES, "created_source")
    body = _body_text(body)
    episode_uid = _optional_text(episode_uid)
    strategy_uid = _optional_uuid(strategy_uid, "strategy_uid")
    entry_uid = _optional_uuid(entry_uid, "entry_uid") or str(uuid4())
    created_at = _timestamp(created_at)
    occurred_at = _timestamp(occurred_at) if occurred_at is not None else None

    if manage_transaction:
        con.execute("BEGIN TRANSACTION")
    try:
        _require_optional_episode(con, episode_uid)
        _require_optional_strategy(con, strategy_uid)
        con.execute(
            "INSERT INTO journal_entries (entry_uid, created_at, created_source) VALUES (?, ?, ?)",
            [entry_uid, created_at, created_source],
        )
        revision = EntryRevision(
            entry_uid=entry_uid,
            revision_no=1,
            episode_uid=episode_uid,
            entry_type=entry_type,
            strategy_uid=strategy_uid,
            title=_optional_text(title),
            body=body,
            occurred_at=occurred_at,
            entry_status="active",
            change_reason=_optional_text(change_reason),
            created_at=created_at,
        )
        _insert_revision(con, revision)
        if manage_transaction:
            con.execute("COMMIT")
        return revision
    except Exception:
        if manage_transaction:
            con.execute("ROLLBACK")
        raise


def append_entry_revision(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_uid: str,
    entry_type: str,
    body: str,
    episode_uid: str | None = None,
    strategy_uid: str | None = None,
    title: str | None = None,
    occurred_at: datetime | None = None,
    entry_status: str = "active",
    change_reason: str | None = None,
    created_at: datetime | None = None,
    manage_transaction: bool = True,
) -> EntryRevision:
    """Append the next complete immutable snapshot for an existing entry."""

    entry_uid = _required_uuid(entry_uid, "entry_uid")
    _enum(entry_type, ENTRY_TYPES, "entry_type")
    _enum(entry_status, ENTRY_STATUSES, "entry_status")
    body = _body_text(body)
    episode_uid = _optional_text(episode_uid)
    strategy_uid = _optional_uuid(strategy_uid, "strategy_uid")
    created_at = _timestamp(created_at)
    occurred_at = _timestamp(occurred_at) if occurred_at is not None else None

    if manage_transaction:
        con.execute("BEGIN TRANSACTION")
    try:
        if con.execute("SELECT COUNT(*) FROM journal_entries WHERE entry_uid = ?", [entry_uid]).fetchone()[0] != 1:
            raise JournalValidationError(f"entry_uid not found: {entry_uid}")
        _require_optional_episode(con, episode_uid)
        _require_optional_strategy(con, strategy_uid)
        current = con.execute(
            "SELECT COALESCE(MAX(revision_no), 0) FROM journal_entry_revisions WHERE entry_uid = ?",
            [entry_uid],
        ).fetchone()[0]
        revision = EntryRevision(
            entry_uid=entry_uid,
            revision_no=int(current) + 1,
            episode_uid=episode_uid,
            entry_type=entry_type,
            strategy_uid=strategy_uid,
            title=_optional_text(title),
            body=body,
            occurred_at=occurred_at,
            entry_status=entry_status,
            change_reason=_optional_text(change_reason),
            created_at=created_at,
        )
        _insert_revision(con, revision)
        if manage_transaction:
            con.execute("COMMIT")
        return revision
    except Exception:
        if manage_transaction:
            con.execute("ROLLBACK")
        raise


def get_current_entry_revision(
    con: duckdb.DuckDBPyConnection,
    entry_uid: str,
) -> EntryRevision:
    """Return the latest immutable snapshot for one logical entry."""

    entry_uid = _required_uuid(entry_uid, "entry_uid")
    row = con.execute(
        """
        SELECT entry_uid, revision_no, episode_uid, entry_type, strategy_uid,
               title, body, occurred_at, entry_status, change_reason, created_at
        FROM journal_entry_revisions
        WHERE entry_uid = ?
        ORDER BY revision_no DESC
        LIMIT 1
        """,
        [entry_uid],
    ).fetchone()
    if row is None:
        raise JournalValidationError(f"entry_uid not found: {entry_uid}")
    return EntryRevision(
        entry_uid=str(row[0]),
        revision_no=int(row[1]),
        episode_uid=str(row[2]) if row[2] is not None else None,
        entry_type=str(row[3]),
        strategy_uid=str(row[4]) if row[4] is not None else None,
        title=str(row[5]) if row[5] is not None else None,
        body=str(row[6]),
        occurred_at=row[7],
        entry_status=str(row[8]),
        change_reason=str(row[9]) if row[9] is not None else None,
        created_at=row[10],
    )


def revise_entry(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_uid: str,
    body: str,
    change_reason: str,
    episode_uid: str | None = None,
    entry_type: str | None = None,
    strategy_uid: str | None = None,
    title: str | None = None,
    occurred_at: datetime | None = None,
    entry_status: str | None = None,
    created_at: datetime | None = None,
) -> EntryRevision:
    """Append a revision, inheriting fields not explicitly replaced.

    `None` means retain the current value. Deliberately clearing an optional
    field is available through the lower-level full-snapshot function.
    """

    current = get_current_entry_revision(con, entry_uid)
    return append_entry_revision(
        con,
        entry_uid=current.entry_uid,
        entry_type=entry_type if entry_type is not None else current.entry_type,
        body=body,
        episode_uid=episode_uid if episode_uid is not None else current.episode_uid,
        strategy_uid=strategy_uid if strategy_uid is not None else current.strategy_uid,
        title=title if title is not None else current.title,
        occurred_at=occurred_at if occurred_at is not None else current.occurred_at,
        entry_status=entry_status if entry_status is not None else current.entry_status,
        change_reason=_required_text(change_reason, "change_reason"),
        created_at=created_at,
    )


def create_strategy(
    con: duckdb.DuckDBPyConnection,
    *,
    name: str,
    description: str = "",
    created_at: datetime | None = None,
) -> str:
    display_name = _required_text(name, "name")
    normalized_name = normalize_catalog_name(display_name)
    created_at = _timestamp(created_at)
    strategy_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_strategies (
            strategy_uid, name, normalized_name, description, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'active', ?, ?)
        """,
        [strategy_uid, display_name, normalized_name, _optional_text(description), created_at, created_at],
    )
    return strategy_uid


def create_tag(
    con: duckdb.DuckDBPyConnection,
    *,
    tag_type: str,
    name: str,
    created_at: datetime | None = None,
) -> str:
    _enum(tag_type, TAG_TYPES, "tag_type")
    display_name = _required_text(name, "name")
    tag_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_tags (
            tag_uid, tag_type, name, normalized_name, status, created_at
        ) VALUES (?, ?, ?, ?, 'active', ?)
        """,
        [tag_uid, tag_type, display_name, normalize_catalog_name(display_name), _timestamp(created_at)],
    )
    return tag_uid


def add_tag_event(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_uid: str,
    tag_uid: str,
    action: str,
    created_at: datetime | None = None,
) -> str:
    entry_uid = _required_uuid(entry_uid, "entry_uid")
    tag_uid = _required_uuid(tag_uid, "tag_uid")
    _enum(action, TAG_ACTIONS, "action")
    if con.execute("SELECT COUNT(*) FROM journal_entries WHERE entry_uid = ?", [entry_uid]).fetchone()[0] != 1:
        raise JournalValidationError(f"entry_uid not found: {entry_uid}")
    if con.execute("SELECT COUNT(*) FROM journal_tags WHERE tag_uid = ?", [tag_uid]).fetchone()[0] != 1:
        raise JournalValidationError(f"tag_uid not found: {tag_uid}")
    current = con.execute(
        """
        SELECT sequence_no, action FROM journal_entry_tag_events
        WHERE entry_uid = ? AND tag_uid = ? ORDER BY sequence_no DESC LIMIT 1
        """,
        [entry_uid, tag_uid],
    ).fetchone()
    if current and current[1] == action:
        raise JournalValidationError(f"tag {tag_uid} is already in action state {action}")
    sequence_no = 1 if current is None else int(current[0]) + 1
    event_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_entry_tag_events (
            tag_event_uid, entry_uid, tag_uid, sequence_no, action, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [event_uid, entry_uid, tag_uid, sequence_no, action, _timestamp(created_at)],
    )
    return event_uid


def register_attachment_metadata(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_uid: str,
    storage_key: str,
    original_filename: str,
    media_type: str,
    byte_size: int,
    content_sha256: str,
    captured_at: datetime | None = None,
    created_at: datetime | None = None,
) -> str:
    """Fail closed until retention, authorization, and storage are approved."""

    validate_attachment_metadata(
        entry_uid=entry_uid,
        storage_key=storage_key,
        original_filename=original_filename,
        media_type=media_type,
        byte_size=byte_size,
        content_sha256=content_sha256,
        captured_at=captured_at,
        created_at=created_at,
    )
    raise JournalPolicyError(
        "journal attachment writes are disabled pending UXJ-05 retention and authorization policy"
    )


def validate_attachment_metadata(
    *,
    entry_uid: str,
    storage_key: str,
    original_filename: str,
    media_type: str,
    byte_size: int,
    content_sha256: str,
    captured_at: datetime | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate proposed attachment metadata without reading or writing content."""

    entry_uid = _required_uuid(entry_uid, "entry_uid")
    storage_key = _required_text(storage_key, "storage_key")
    storage_path = PurePosixPath(storage_key)
    if storage_path.is_absolute() or "://" in storage_key or ".." in storage_path.parts:
        raise JournalValidationError("storage_key must be an opaque relative private-store key")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
        raise JournalValidationError("byte_size must be a non-negative integer")
    original_filename = _required_text(original_filename, "original_filename")
    if (
        original_filename in {".", ".."}
        or "/" in original_filename
        or "\\" in original_filename
        or "\x00" in original_filename
    ):
        raise JournalValidationError("original_filename must be a sanitized display filename")
    media_type = _required_text(media_type, "media_type").casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", media_type):
        raise JournalValidationError("media_type must be a valid lowercase MIME type")
    if len(content_sha256) != 64 or content_sha256.lower() != content_sha256:
        raise JournalValidationError("content_sha256 must be a 64-character lowercase hash")
    try:
        int(content_sha256, 16)
    except ValueError as exc:
        raise JournalValidationError("content_sha256 must contain lowercase hexadecimal characters") from exc
    return {
        "entry_uid": entry_uid,
        "storage_key": storage_key,
        "original_filename": original_filename,
        "media_type": media_type,
        "byte_size": byte_size,
        "content_sha256": content_sha256,
        "captured_at": _timestamp(captured_at) if captured_at is not None else None,
        "created_at": _timestamp(created_at),
    }


def _current_review_head(con: duckdb.DuckDBPyConnection, episode_uid: str) -> str | None:
    heads = con.execute(
        """
        SELECT r.review_uid
        FROM journal_reviews r
        WHERE r.episode_uid = ?
          AND NOT EXISTS (
              SELECT 1 FROM journal_reviews child
              WHERE child.supersedes_review_uid = r.review_uid
          )
        """,
        [episode_uid],
    ).fetchall()
    if len(heads) > 1:
        raise JournalIntegrityError(f"multiple current review heads for episode_uid {episode_uid}")
    return str(heads[0][0]) if heads else None


def _insert_revision(con: duckdb.DuckDBPyConnection, revision: EntryRevision) -> None:
    con.execute(
        """
        INSERT INTO journal_entry_revisions (
            entry_uid, revision_no, episode_uid, entry_type, strategy_uid, title,
            body, occurred_at, entry_status, change_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            revision.entry_uid,
            revision.revision_no,
            revision.episode_uid,
            revision.entry_type,
            revision.strategy_uid,
            revision.title,
            revision.body,
            revision.occurred_at,
            revision.entry_status,
            revision.change_reason,
            revision.created_at,
        ],
    )


def _require_episode(con: duckdb.DuckDBPyConnection, episode_uid: str) -> None:
    if con.execute("SELECT COUNT(*) FROM trade_episodes WHERE episode_uid = ?", [episode_uid]).fetchone()[0] != 1:
        raise JournalValidationError(f"episode_uid not found: {episode_uid}")


def _require_optional_episode(con: duckdb.DuckDBPyConnection, episode_uid: str | None) -> None:
    if episode_uid is not None:
        _require_episode(con, episode_uid)


def _require_optional_strategy(con: duckdb.DuckDBPyConnection, strategy_uid: str | None) -> None:
    if strategy_uid is None:
        return
    if con.execute("SELECT COUNT(*) FROM journal_strategies WHERE strategy_uid = ?", [strategy_uid]).fetchone()[0] != 1:
        raise JournalValidationError(f"strategy_uid not found: {strategy_uid}")


def _enum(value: str, allowed: frozenset[str], field: str) -> str:
    normalized = _required_text(value, field)
    if normalized not in allowed:
        raise JournalValidationError(f"{field} must be one of {sorted(allowed)}; got {value!r}")
    return normalized


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise JournalValidationError(f"{field} must not be empty")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _body_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _required_uuid(value: Any, field: str) -> str:
    normalized = _required_text(value, field)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise JournalValidationError(f"{field} must be a valid UUID") from exc


def _optional_uuid(value: Any, field: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _required_uuid(value, field)


def _timestamp(value: datetime | None) -> datetime:
    if value is None:
        return utc_now_naive()
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
