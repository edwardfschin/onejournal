# OneJournal Review and Learning Workflows

## Scope

This runbook describes the local single-owner UXJ-02 through UXJ-06
foundation. It does not authorize runtime database migration, attachment
storage, public journal output, broker access, or trading.

## Impact map

- Authoritative source: DuckDB journal tables and append-only history.
- Upstream producer: validated trade episodes, manual review saves, and private
  owner-authored journal actions.
- Changed components: journal domain/search/routine services, migrations 0005
  through 0007, DB dashboard review-queue metadata, and the internal Streamlit
  prototype.
- Downstream consumers: review queue/navigation, private structured entry
  search, and local operator workflows.
- Persisted state: journal entry/review history, saved filter definitions,
  process goals, habits, and explicit-period review events.
- User-facing surfaces: internal Streamlit only. ADR-0017 selects the
  production web/API foundation, but no production frontend or API is
  implemented and the authentication/security design remains pending.
- Validation: migration, domain, queue, search, replay, payload privacy,
  routine, and full regression tests on temporary databases.
- Rollback: restore a verified pre-migration database backup or use a reviewed
  forward corrective migration; no destructive down migration exists.

## Review queues

`journal_review_queue` is a derived, non-authoritative dashboard view. It never
contains `entry_reason`, `notes`, journal body text, attachment metadata, or
storage keys. Each item includes its queue and one or more reason codes.

| Queue | Membership evidence |
|---|---|
| `unreviewed` | No compatibility review row (`missing_review`) or current status `unreviewed` (`unreviewed_status`). |
| `incomplete` | Current review status is `needs_review` (`needs_review_status`). |
| `risk_flagged` | Poor/mistake setup quality, mistake-review status, active `Risk` general tag, active mistake entry, or active mistake tag. |
| `mistake` | Mistake setup quality, mistake-review status, active mistake entry, or active mistake tag. |

Ordering is deterministic: newest episode opening time first, then
`episode_uid`. A trade may legitimately appear in more than one queue because
each queue expresses a different action or risk reason.

## Structured journal entries

Supported entry types include pre-trade plan, entry thesis, execution review,
exit review, post-trade reflection, weekly/monthly review, mistake, lesson, and
note. Every edit appends a full immutable snapshot. Earlier revisions remain
available and episode rebuilds do not cascade-delete entries.

The internal Streamlit prototype can create private entries after migration
0005. The local operator command can create or revise an entry while reading
body content from a file or standard input and never printing it:

```text
python scripts/journal/upsert_journal_entry_to_db.py --db <temporary-or-approved-db> create --entry-type entry_thesis --body-file <private-file>
```

Keep private body files outside the repository and delete them according to the
eventual approved retention policy; this command does not manage source files.

Do not run the command against the runtime journal until migrations 0005–0007
have been rehearsed on a realistic copy, backed up, and explicitly approved.

## Search and saved views

Private search supports text, date, symbol, broker, account, system strategy,
owner strategy, review state, review queue, and entry type. Search reads only
current active entry revisions. Unlinked pre-trade/general entries remain
searchable.

Saved views persist validated structured filter definitions. They do not cache
results or copy journal prose, attachment keys, broker payloads, or financial
values. Search results can contain private narrative and therefore must not be
added to generated dashboard output or an unauthenticated API.

## Attachment boundary (UXJ-05)

Migration 0005 defines metadata fields and validation only. Attachment writes,
uploads, retrieval, previews, public links, and deletion all fail closed. UXJ-05
cannot complete until storage, authorization, encryption, retention, deletion,
backup, and incident-response policy is approved.

## Goals, habits, and recurring reviews (UXJ-06)

Migration 0007 provides process-only goals, append-only goal check-ins, habits,
habit completion/revocation history, and explicit-period weekly/monthly review
events. Callers must supply `period_start`, `period_end`, and `due_date`; the
system does not silently choose timezone or calendar-boundary policy.

Financial goal evaluation fails closed. It cannot use portfolio metrics until
PNL-02 market-data/freshness policy and PNL-07 reporting-period/export policy
are approved and canonical metrics reconcile.

## Runtime migration gate

The observed runtime database predates the durable journal migrations. The
Streamlit prototype detects that state and leaves new structured features
unavailable instead of applying schema changes automatically. A live migration
requires the separate migration workflow and explicit approval.
