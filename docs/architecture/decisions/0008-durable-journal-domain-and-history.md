# ADR-0008: Define the durable journal domain and history model

- Status: Accepted
- Date: 2026-08-09
- Decision owners: OneJournal project owner
- Related roadmap items: UXJ-01 through UXJ-05
- Related contracts: `docs/journal_domain_contract_v1.md`,
  `docs/dashboard_db_contract.md`, `docs/manual_review_workflow.md`, ADR-0002,
  ADR-0006
- Supersedes: None
- Superseded by: None

## Context

The current editable journal state is one row per trade episode in DuckDB
`manual_reviews`. Streamlit saves `review_status`, `setup_quality`,
`entry_reason`, and `notes` through `upsert_manual_review_to_db.py`, which uses
`INSERT OR REPLACE`. The DB dashboard builder then joins that current row to
`trade_episodes`. CSV reviews are legacy/backfill only.

This flow is useful for the internal prototype, but it cannot preserve edit
history, represent several entries for one trade, support pre-trade notes before
an episode exists, distinguish reusable strategies/tags from narrative text, or
record attachment lineage safely. Rebuilding trade episodes must not erase
authored journal content.

The local runtime database observed during this review is at migration `0002`
with eight `manual_reviews` rows. Repository migrations currently extend
through `0004`. No live migration is authorized by this proposal.

ADR-0002 fixes the initial product scope at one authenticated owner with
multiple owned brokerage accounts. It explicitly defers multi-user tenancy.
The journal model therefore must not invent a multi-tenant authorization policy,
but it must remain migratable when that policy is eventually approved.

## Decision

OneJournal will use the following model.

1. A journal entry is an owner-authored logical record with an immutable
   `entry_uid`. It can exist before a broker trade and may later link to one
   `trade_episodes.episode_uid`.
2. Entry content is append-only by revision. Editing creates the next revision;
   it never overwrites or deletes the earlier text.
3. Structured episode reviews are append-only review events. The latest valid
   event is the current review state.
4. Episode links are durable logical references without delete-cascade
   behavior. A rebuild may temporarily orphan a link; the journal record is
   retained and the orphan is surfaced for reconciliation.
5. `manual_reviews` remains a compatibility projection during the Streamlit
   transition. A Save Review operation writes the append-only review event and
   updates the projection in one transaction.
6. System-derived `trade_episodes.strategy_type` and `strategy_label` remain
   canonical classification evidence. Owner-defined journal strategies are a
   separate catalog and never overwrite the derived classification.
7. Mistakes and lessons are journal entry types and may also use typed reusable
   tags. They are not embedded in financial or broker records.
8. Attachments are private journal evidence. DuckDB stores metadata and a
   private storage key only; it does not store file bytes, machine-absolute
   paths, public URLs, credentials, or broker payloads.
9. Attachment upload, serving, deletion, and retention remain disabled until
   UXJ-05 and the production authorization/retention decisions are approved.
10. Journal narrative and attachment metadata are not added to the existing
   dashboard payload by this decision. A later authenticated API contract must
   explicitly authorize each field.

The field-level model and representative examples are defined in
`docs/journal_domain_contract_v1.md`.

## Boundaries

This decision covers the local single-owner journal domain, identities,
revision history, episode linkage, strategies, typed tags, review events, and
attachment metadata.

It does not approve:

- multi-user tenancy or sharing
- attachment upload, download, previews, public links, or deletion
- retention duration, legal hold, backup retention, or account closure policy
- production authentication or authorization
- UI design or a production frontend stack
- journal-data inclusion in reports, exports, or public payloads
- broker writes, paper trading, or live trading

## Alternatives considered

### Continue replacing one `manual_reviews` row

This is simple and already works in Streamlit, but loses edit history, cannot
model multiple narrative entries, and makes future review workflows depend on a
prototype projection. Rejected as the durable model; retained temporarily for
compatibility.

### Store each entry as one mutable JSON document

This reduces tables but makes validation, history, tags, attachment lineage,
and deterministic querying harder. A corrected schema would require rewriting
opaque documents. Rejected.

### Build full multi-user and attachment infrastructure now

This would require tenancy, authorization, storage, encryption, retention,
deletion, and incident-response policy before the first single-owner journal is
stable. Rejected for UXJ-01.

### Recommended normalized, append-only history model

Stable identities plus append-only entry revisions and review events preserve
history while keeping the current Streamlit projection compatible. Separate
strategy/tag catalogs support search and analytics without putting presentation
labels into broker records. Recommended.

## Consequences

### Positive

- Authored text survives episode rebuilds and review edits.
- Pre-trade and general journal entries do not depend on a broker fill already
  existing.
- System classification and owner intent remain distinguishable.
- Mistakes, lessons, tags, and strategies become queryable without parsing
  prose.
- Attachment content stays outside Git, payloads, and the database.

### Negative and trade-offs

- Save Review becomes a transactional dual-write during the compatibility
  period.
- Current-state queries require an explicitly defined latest-event/latest-
  revision rule.
- A later tenancy decision will require owner partitioning and authorization
  migration.
- Attachment features remain unavailable until UXJ-05 and retention/security
  policy are approved.

## Compatibility and migration

Migration `0005` adds new tables without changing or dropping
existing tables. It will backfill one append-only review event for each existing
`manual_reviews` row, preserving the original `updated_at`. It will not convert
legacy `entry_reason` or `notes` into separate narrative entries because doing
so would invent semantics; those values remain on the structured review event.

The existing payload and Streamlit fields remain unchanged during the
transition. Import/replay must continue preserving both `manual_reviews` and
the new journal tables. No live database migration occurs without a verified
backup, temporary-copy rehearsal, explicit approval, and post-migration checks.

## Security, privacy, and financial impact

Journal prose, mistakes, lessons, screenshots, and attachments can contain
highly sensitive personal and financial information. They must not appear in
Git, logs, errors, unauthenticated payloads, screenshots, fixtures, or public
URLs. Content-access policy fails closed until production authentication and
authorization exist.

Journal records annotate canonical financial evidence; they do not alter fills,
positions, lifecycle events, P&L, or broker state. No journal operation may call
a broker order endpoint.

## Validation

Accepted implementation must prove on temporary databases that:

- existing review rows are preserved and backfilled exactly once
- migration `0005` is transactional and idempotent through the migration ledger
- every entry revision belongs to a stable entry identity
- latest revision and latest review state are deterministic
- invalid entry/review/tag/attachment values fail before writing
- missing episode, strategy, entry, and tag references fail closed
- episode rebuilds retain journal records and report any orphaned link
- Save Review writes the event and compatibility projection atomically
- replay/replacement imports preserve all journal-domain tables
- current dashboard payload and Streamlit review behavior remain compatible
- private content and attachment storage keys are absent from public/generated
  payloads and test fixtures
- focused migration/domain/integration tests and the full clean suite pass

## Rollback or supersession

Before a live migration, restore readiness requires a verified pre-migration
database backup and a documented restoration check. OneJournal will not use a
destructive down migration. If post-migration writes must be preserved, rollback
uses a separately reviewed forward corrective migration.

A later accepted tenancy, retention, or attachment-storage ADR may supersede the
relevant boundaries of this decision.
