# OneJournal Journal Migrations

This directory is reserved for ordered DuckDB migration artifacts governed by
`docs/database_migrations.md`.

There are currently twelve migration files:

- `0001_establish_schema_version.sql`:
  create the migration ledger (`schema_migrations`) with run metadata and audit
  fields.
- `0002_add_normalized_accounts_orders_positions_transactions.sql`:
  add broker-neutral `normalized_accounts`, `normalized_orders`,
  `normalized_positions`, and `normalized_transactions` with `import_runs`
  lineage.
- `0003_add_normalized_fill_revisions.sql`:
  add broker-neutral `normalized_fill_revisions` to preserve prior fill rows
  during correction-safe replace re-imports without dropping manual reviews.
- `0004_add_normalized_lifecycle_events.sql`:
  add `normalized_lifecycle_events` for ADR-0005 lifecycle-event ledger persistence
  with import lineage and as-of/ingest metadata.
- `0005_add_durable_journal_domain.sql`:
  add ADR-0008 stable journal entry identities, append-only entry revisions and
  review events, owner-defined strategies, typed tags and tag-event history,
  and attachment metadata whose writes remain disabled pending UXJ-05 policy.
- `0006_add_journal_saved_views.sql`:
  add private, structured UXJ-04 search-filter definitions without storing
  query results, journal prose, attachment keys, or broker payloads.
- `0007_add_journal_goals_habits_reviews.sql`:
  add process-only goals, append-only check-ins, habits, habit events, and
  explicit-period weekly/monthly review events; financial evaluation remains
  disabled pending PNL-02 and PNL-07.
- `0008_add_lifecycle_event_legs.sql`:
  add identity-stable, decimal-safe transfer-item evidence linked to lifecycle event
  headers without inferring assignment, exercise, expiration, or corporate-
  action P&L.
- `0009_add_utc_financial_event_instants.sql`:
  add canonical UTC ISO-8601 evidence fields for fill, fetch, and lifecycle
  ordering without guessing how to reinterpret legacy timezone-less values.
- `0010_add_approved_lifecycle_pnl_allocations.sql`:
  add reviewed lifecycle instructions, predecessor/source-leg links, immutable
  calculation runs, input fingerprints, group results, closed-lot lineage, and
  assignment/exercise/expiration allocation lineage under accepted ADR-0004.
- `0011_add_normalized_market_quotes.sql`:
  add provider/connection-scoped quote ingestion audit runs and normalized,
  broker-independent top-of-book evidence with UTC timestamps, entitlement,
  delay/session state, immutable raw lineage, and adapter version.
- `0012_add_quote_capture_envelope.sql`:
  add the provider-neutral capture contract version, exact request scope,
  receive time, checksum-bound source storage/locator, and full-envelope replay
  lineage to quote ingestion runs without rewriting migration 0011 or existing
  quote rows.

The existing DuckDB schema is a prototype bootstrap baseline created (and now
versioned) by `scripts/journal/init_journal_db.py`.

JRN-01 uses this directory for controlled, tested schema versioning on
temporary database copies before any live database migration.

Do not add or execute a migration without:

- complete producer, consumer, schema, and data-flow understanding
- an impact map
- temporary-copy rehearsal
- backup and restoration planning
- proportional automated validation
- explicit approval before applying it to the live journal
