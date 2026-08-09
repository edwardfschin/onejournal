"""OneJournal minimal Streamlit dashboard.

Purpose
-------
Display the published dashboard payload and allow manual journal review edits.

Phase E operator contract:
- DB payload is the only writable review mode.
- Save Review appends DuckDB journal_reviews and updates manual_reviews.
- Save Review rebuilds dashboard_payload_from_db.json.
- CSV and Custom payloads are read-only.
- No broker API calls.
- No order placement.
- No order cancellation.
- No order modification.
- No auto-trade.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import streamlit as st
import duckdb

from onejournal.journal.domain import JournalPolicyError, create_entry, table_exists
from onejournal.journal.search import (
    JournalSearchFilters,
    create_saved_view,
    list_saved_views,
    load_saved_view,
    search_journal,
)


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PAYLOAD_PATH = Path(
    os.environ.get(
        "ONEJOURNAL_CSV_PAYLOAD_PATH",
        PROJECT_DIR / "output/dashboard/latest/dashboard_payload.json",
    )
)
DEFAULT_DB_PAYLOAD_PATH = Path(
    os.environ.get(
        "ONEJOURNAL_DB_PAYLOAD_PATH",
        PROJECT_DIR / "output/dashboard/latest/dashboard_payload_from_db.json",
    )
)
DEFAULT_DB_PATH = Path(
    os.environ.get(
        "ONEJOURNAL_DB_PATH",
        PROJECT_DIR / "data/journal/onejournal.duckdb",
    )
)
REVIEW_STATUS_LABELS = {
    "Not Reviewed": "unreviewed",
    "Reviewed": "reviewed",
    "Needs Review": "needs_review",
    "Mistake Review": "mistake_review",
}
SETUP_QUALITY_LABELS = {
    "Unknown": "unknown",
    "Good": "good",
    "Acceptable": "acceptable",
    "Poor": "poor",
    "Mistake": "mistake",
}
REVIEW_STATUSES = list(REVIEW_STATUS_LABELS)
SETUP_QUALITIES = list(SETUP_QUALITY_LABELS)
QUALITY_STATES = ("valid", "stale", "incomplete", "reconciliation_pending", "unavailable", "failed")
QUALITY_STATE_LABELS = {
    "valid": "✅ Valid",
    "stale": "🕒 Stale",
    "incomplete": "⚠️ Incomplete",
    "reconciliation_pending": "🔎 Reconciliation Pending",
    "unavailable": "❓ Unavailable",
    "failed": "❌ Failed",
}
ENTRY_TYPE_LABELS = {
    "Pre-trade Plan": "pre_trade_plan",
    "Entry Thesis": "entry_thesis",
    "Execution Review": "execution_review",
    "Exit Review": "exit_review",
    "Post-trade Reflection": "post_trade_reflection",
    "Weekly Review": "weekly_review",
    "Monthly Review": "monthly_review",
    "Mistake": "mistake",
    "Lesson": "lesson",
    "Note": "note",
}
QUEUE_LABELS = {
    "All Trades": None,
    "Unreviewed": "unreviewed",
    "Incomplete": "incomplete",
    "Risk Flagged": "risk_flagged",
    "Mistakes": "mistake",
}


def load_payload(path: Path) -> dict[str, Any]:
    """Load dashboard payload JSON."""

    if not path.exists():
        raise FileNotFoundError(f"Dashboard payload not found: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def money(value: Any) -> str:
    """Format dashboard money-like values."""

    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def refresh_db_dashboard_payload(
    asof: str,
    db_path: Path,
    payload_path: Path,
    episode_uid: str,
    review_status: str,
    setup_quality: str,
    entry_reason: str,
    notes: str,
) -> subprocess.CompletedProcess[str]:
    """Write one review to DuckDB, then rebuild the DB dashboard payload."""

    upsert_cmd = [
        sys.executable,
        str(PROJECT_DIR / "scripts/journal/upsert_manual_review_to_db.py"),
        "--db",
        str(db_path),
        "--episode-uid",
        episode_uid,
        "--review-status",
        review_status,
        "--setup-quality",
        setup_quality,
        "--entry-reason",
        entry_reason,
        "--notes",
        notes,
    ]
    upsert_result = subprocess.run(upsert_cmd, text=True, capture_output=True, cwd=str(PROJECT_DIR))
    if upsert_result.returncode != 0:
        return upsert_result

    build_cmd = [
        sys.executable,
        str(PROJECT_DIR / "scripts/journal/build_dashboard_payload_from_db.py"),
        "--asof",
        asof,
        "--db",
        str(db_path),
        "--output",
        str(payload_path),
        "--write",
    ]
    build_result = subprocess.run(build_cmd, text=True, capture_output=True, cwd=str(PROJECT_DIR))
    build_result.stdout = (upsert_result.stdout or "") + "\n" + (build_result.stdout or "")
    build_result.stderr = (upsert_result.stderr or "") + "\n" + (build_result.stderr or "")
    return build_result


def build_episode_display_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw payload episode rows into friendly dashboard rows."""

    rows: list[dict[str, Any]] = []

    for episode in episodes:
        rows.append(
            {
                "Strategy": episode.get("strategy_label", "Unknown"),
                "Review": _label_for_value(REVIEW_STATUS_LABELS, episode.get("review_status", "unreviewed")),
                "Setup Quality": _label_for_value(SETUP_QUALITY_LABELS, episode.get("setup_quality", "unknown")),
                "Symbol": episode.get("primary_symbol", "-"),
                "Status": episode.get("status", "-"),
                "Legs": episode.get("leg_count", episode.get("net_quantity", "0")),
                "Leg Summary": episode.get("leg_summary", episode.get("primary_symbol", "-")),
                "Net Cashflow": episode.get("cashflow_label", money(episode.get("gross_cashflow", "0"))),
                "Commission": money(episode.get("commission", "0")),
                "Fees": money(episode.get("fees", "0")),
                "Opened At": episode.get("opened_at", "-"),
                "Source": episode.get("source_broker", "-"),
            }
        )

    return rows


def _label_for_value(mapping: dict[str, str], value: str) -> str:
    """Return friendly label for stored machine value."""

    for label, stored_value in mapping.items():
        if stored_value == value:
            return label
    return next(iter(mapping))


def _quality_label(status: str) -> str:
    return QUALITY_STATE_LABELS.get(status, f"({status})")


def _render_quality_status(metadata: dict[str, Any], payload_source: str) -> None:
    quality = metadata.get("quality")
    if not isinstance(quality, dict):
        return
    overall_status = str(quality.get("overall_status", "unavailable"))
    if overall_status not in QUALITY_STATES:
        overall_status = "failed"

    checks = quality.get("checks", {})
    trade_summary_status = quality.get("trade_summary_status", {})

    st.subheader(f"Dataset quality: {_quality_label(overall_status)}")
    st.caption(f"Payload source: {payload_source}")

    if overall_status != "valid":
        st.warning("Some dashboard values were generated with dataset conditions that are not fully authoritative.")

    if isinstance(checks, dict) and checks:
        with st.expander("Quality checks", expanded=overall_status != "valid"):
            for check_name in ("import", "asof", "pnl"):
                check = checks.get(check_name, {})
                status = str(check.get("status", "unavailable"))
                if status not in QUALITY_STATES:
                    status = "failed"
                reason = check.get("reason")
                text = f"{check_name}: {_quality_label(status)}"
                if reason:
                    text += f" — {reason}"
                st.text(text)

    if isinstance(trade_summary_status, dict):
        st.json({
            metric: _quality_label(str(metric_status) if str(metric_status) in QUALITY_STATES else "failed")
            for metric, metric_status in trade_summary_status.items()
        })


def render_review_editor(episodes: list[dict[str, Any]], payload_path: Path, asof: str, payload_source: str, db_path: Path) -> None:
    """Render manual review editor."""

    if not episodes:
        return

    st.subheader("Update Trade Review")
    if payload_source != "DB payload":
        st.info("CSV and Custom payloads are read-only in Phase B. Select DB payload to save reviews.")
        st.caption("CSV payload is legacy/backfill/export only. No broker action is taken.")
        return

    st.success("Writable mode: DB payload only. Save Review appends durable history, updates the compatibility projection, and rebuilds dashboard_payload_from_db.json.")
    st.caption("Safety: no broker API call, no order placement, no order cancellation, no order modification, no auto-trade.")

    labels = []
    episode_by_label: dict[str, dict[str, Any]] = {}
    for episode in episodes:
        episode_uid = str(episode.get("episode_uid") or episode.get("primary_symbol") or "")
        label = f"{episode.get('strategy_label', 'Unknown')} | {episode.get('primary_symbol', episode_uid)}"
        labels.append(label)
        episode_by_label[label] = episode

    selected_label = st.selectbox("Trade episode", labels, key="review_episode_selector")
    selected = episode_by_label[selected_label]
    episode_uid = str(selected.get("episode_uid") or selected.get("primary_symbol") or "")

    with st.form("manual_review_form"):
        review_status_label = st.selectbox(
            "Review Status",
            REVIEW_STATUSES,
            index=REVIEW_STATUSES.index(_label_for_value(REVIEW_STATUS_LABELS, str(selected.get("review_status", "unreviewed")))),
            key=f"review_status_{episode_uid}",
        )
        setup_quality_label = st.selectbox(
            "Setup Quality",
            SETUP_QUALITIES,
            index=SETUP_QUALITIES.index(_label_for_value(SETUP_QUALITY_LABELS, str(selected.get("setup_quality", "unknown")))),
            key=f"setup_quality_{episode_uid}",
        )
        review_status = REVIEW_STATUS_LABELS[review_status_label]
        setup_quality = SETUP_QUALITY_LABELS[setup_quality_label]
        entry_reason = st.text_input("Entry Reason", str(selected.get("entry_reason", "")), key=f"entry_reason_{episode_uid}")
        notes = st.text_area("Notes", str(selected.get("notes", "")), height=120, key=f"notes_{episode_uid}")
        submitted = st.form_submit_button("Save Review to DuckDB")

    if submitted:
        result = refresh_db_dashboard_payload(
            asof,
            db_path,
            payload_path,
            episode_uid,
            review_status,
            setup_quality,
            entry_reason,
            notes,
        )
        st.info(f"Saved DB review history and compatibility projection for: {episode_uid}")
        st.caption(f"DB path: {db_path}")
        st.caption(f"Payload path: {payload_path}")
        st.caption(f"Refresh return code: {result.returncode}")
        if result.stdout:
            st.code(result.stdout, language="text")
        if result.stderr:
            st.code(result.stderr, language="text")
        if result.returncode == 0:
            st.session_state["last_review_save"] = f"Saved review for {episode_uid}"
            st.rerun()
        else:
            st.error("Review upsert or DB dashboard refresh failed. See output above.")


def journal_domain_available(db_path: Path) -> bool:
    """Return whether the runtime DB has the durable journal schema."""

    if not db_path.exists():
        return False
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return table_exists(con, "journal_entry_revisions")
    finally:
        con.close()


def filter_episodes_by_queue(
    episodes: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
    queue_name: str | None,
) -> list[dict[str, Any]]:
    """Filter payload episodes using traceable queue membership only."""

    if queue_name is None:
        return episodes
    episode_uids = {
        str(row.get("episode_uid"))
        for row in queue_items
        if row.get("queue") == queue_name
    }
    return [row for row in episodes if str(row.get("episode_uid")) in episode_uids]


def render_review_queue_selector(
    episodes: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render deterministic queue counts and return the selected episode scope."""

    counts = {
        queue_name: sum(1 for row in queue_items if row.get("queue") == queue_name)
        for queue_name in (value for value in QUEUE_LABELS.values() if value is not None)
    }
    labels = [
        label if queue_name is None else f"{label} ({counts.get(queue_name, 0)})"
        for label, queue_name in QUEUE_LABELS.items()
    ]
    selected_label = st.selectbox("Review queue", labels, key="review_queue_selector")
    base_label = next(label for label in QUEUE_LABELS if selected_label.startswith(label))
    return filter_episodes_by_queue(episodes, queue_items, QUEUE_LABELS[base_label])


def render_structured_journal(db_path: Path, episodes: list[dict[str, Any]]) -> None:
    """Render the private UXJ-03/04 local prototype workflow."""

    st.subheader("Structured Journal")
    st.caption(
        "Private local prototype. Journal text is read from DuckDB directly and is not added to the dashboard payload."
    )
    if not journal_domain_available(db_path):
        st.info(
            "Structured journal is unavailable until migration 0005 is explicitly applied to the runtime database."
        )
        return

    create_tab, search_tab = st.tabs(["New Entry", "Search Journal"])
    with create_tab:
        episode_options = {"Unlinked / pre-trade": None}
        for episode in episodes:
            episode_uid = str(episode.get("episode_uid", ""))
            label = f"{episode.get('primary_symbol', '-')} | {episode.get('strategy_label', '-')} | {episode_uid}"
            episode_options[label] = episode_uid
        with st.form("structured_journal_create_form"):
            entry_type_label = st.selectbox("Entry type", list(ENTRY_TYPE_LABELS))
            episode_label = st.selectbox("Linked trade", list(episode_options))
            title = st.text_input("Title")
            body = st.text_area("Private journal entry", height=180)
            submitted = st.form_submit_button("Save Private Journal Entry")
        if submitted:
            try:
                con = duckdb.connect(str(db_path))
                try:
                    revision = create_entry(
                        con,
                        entry_type=ENTRY_TYPE_LABELS[entry_type_label],
                        body=body,
                        title=title,
                        episode_uid=episode_options[episode_label],
                        created_source="streamlit",
                    )
                finally:
                    con.close()
                st.success(f"Saved entry {revision.entry_uid} revision {revision.revision_no}.")
            except Exception as exc:
                st.error(f"Journal entry was not saved ({type(exc).__name__}). Private content was not logged.")

    with search_tab:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            saved_views = list_saved_views(con)
        finally:
            con.close()
        saved_view_options = {"None": None}
        saved_view_options.update(
            {row["name"]: row["saved_view_uid"] for row in saved_views}
        )
        selected_saved_view = st.selectbox(
            "Saved view",
            list(saved_view_options),
            key="journal_saved_view_selector",
        )
        run_saved_view = st.button(
            "Run Saved View",
            disabled=saved_view_options[selected_saved_view] is None,
        )
        with st.form("structured_journal_search_form"):
            query_text = st.text_input("Search title or journal text")
            symbol = st.text_input("Symbol")
            review_status = st.selectbox(
                "Review state",
                ["Any", *REVIEW_STATUSES],
            )
            entry_type_label = st.selectbox(
                "Entry type",
                ["Any", *ENTRY_TYPE_LABELS],
                key="journal_search_entry_type",
            )
            saved_view_name = st.text_input("Save these filters as (optional)")
            search_submitted = st.form_submit_button("Search Private Journal")
            save_submitted = st.form_submit_button("Save View and Search")
        filters = JournalSearchFilters(
            query_text=query_text or None,
            symbol=symbol or None,
            review_status=(
                None if review_status == "Any" else REVIEW_STATUS_LABELS[review_status]
            ),
            entry_type=(
                None if entry_type_label == "Any" else ENTRY_TYPE_LABELS[entry_type_label]
            ),
        )
        result = None
        try:
            if run_saved_view:
                con = duckdb.connect(str(db_path), read_only=True)
                try:
                    _, filters = load_saved_view(
                        con,
                        str(saved_view_options[selected_saved_view]),
                    )
                    result = search_journal(con, filters)
                finally:
                    con.close()
            elif search_submitted or save_submitted:
                if save_submitted:
                    if not saved_view_name.strip():
                        raise ValueError("a saved-view name is required")
                    con = duckdb.connect(str(db_path))
                    try:
                        create_saved_view(con, name=saved_view_name, filters=filters)
                    finally:
                        con.close()
                    st.success(f"Saved view: {saved_view_name.strip()}")
                con = duckdb.connect(str(db_path), read_only=True)
                try:
                    result = search_journal(con, filters)
                finally:
                    con.close()
            if result is not None:
                _render_journal_search_result(result)
        except (JournalPolicyError, ValueError, duckdb.Error) as exc:
            st.error(f"Journal search or saved-view action failed: {exc}")


def _render_journal_search_result(result: Any) -> None:
    st.caption(
        f"Found {len(result.episodes)} trade(s) and {len(result.entries)} current journal entry/entries."
    )
    for entry in result.entries:
        heading = entry.get("title") or entry.get("entry_type") or "Journal entry"
        st.markdown(f"**{heading}**")
        st.caption(
            f"{entry.get('entry_type')} | revision {entry.get('revision_no')} | "
            f"symbol {entry.get('primary_symbol') or 'unlinked'}"
        )
        st.write(entry.get("body", ""))


def main() -> None:
    """Run the OneJournal Streamlit dashboard."""

    st.set_page_config(
        page_title="OneJournal",
        page_icon="📘",
        layout="wide",
    )

    st.title("📘 OneJournal")
    st.caption("Internal prototype — broker-independent trading journal dashboard")

    payload_source = st.sidebar.radio(
        "Payload source",
        ["DB payload", "CSV payload", "Custom path"],
        index=0,
        help="DB payload is the default. Save Review appends durable history and updates the compatibility projection. CSV payload is legacy/backfill.",
    )
    if payload_source == "CSV payload":
        payload_path = DEFAULT_PAYLOAD_PATH
        st.sidebar.caption(f"Payload path: {payload_path}")
    elif payload_source == "DB payload":
        payload_path = DEFAULT_DB_PAYLOAD_PATH
        st.sidebar.caption(f"Payload path: {payload_path}")
    else:
        payload_path = Path(st.sidebar.text_input("Payload path", str(DEFAULT_PAYLOAD_PATH)))
    
    try:
        payload = load_payload(payload_path)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    metadata = payload.get("metadata", {})
    trade_summary = payload.get("trade_summary", {})
    episodes = payload.get("recent_trade_episodes", [])
    queue_items = payload.get("journal_review_queue", [])

    mode = metadata.get("mode", "unknown")
    auto_trade = metadata.get("auto_trade", "unknown")
    asof = str(metadata.get("asof", ""))

    st.warning(
        "Internal prototype only. Read-only journal view. "
        "No order placement, no order cancellation, and no auto-trade."
    )
    st.info(f"Mode: {mode} | Auto-trade: {auto_trade} | Payload source: {payload_source}")

    if payload_source == "DB payload":
        _render_quality_status(metadata, payload_source)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("As of", metadata.get("asof", "-"))
    col2.metric("Gross Cashflow", money(trade_summary.get("gross_cashflow", "0")))
    col3.metric("Commission", money(trade_summary.get("commission", "0")))
    col4.metric("Fees", money(trade_summary.get("fees", "0")))

    if st.session_state.get("last_review_save"):
        st.success(st.session_state.pop("last_review_save"))

    st.subheader("Recent Trade Episodes")

    if episodes:
        visible_episodes = render_review_queue_selector(episodes, queue_items)
        st.dataframe(
            build_episode_display_rows(visible_episodes),
            width="stretch",
            hide_index=True,
        )
        if visible_episodes:
            render_review_editor(visible_episodes, payload_path, asof, payload_source, DEFAULT_DB_PATH)
        else:
            st.info("No trades are currently in this review queue.")
        if payload_source == "DB payload":
            render_structured_journal(DEFAULT_DB_PATH, episodes)
    else:
        st.warning("No recent trade episodes found.")

    with st.expander("Payload metadata", expanded=False):
        st.json(metadata)


if __name__ == "__main__":
    main()
