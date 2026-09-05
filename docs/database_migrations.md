# OneJournal Database Migration Convention

## Current state

`scripts/journal/init_journal_db.py` now routes bootstrap and version alignment
through the journal migration runner and the migration artifact set:

- `import_runs`
- `normalized_fills`
- `manual_reviews`
- `trade_episodes`
- `trade_episode_legs`
- `normalized_accounts`
- `normalized_orders`
- `normalized_positions`
- `normalized_transactions`
- `normalized_lifecycle_events`
- `normalized_lifecycle_event_legs`
- `approved_option_lifecycle_events`
- `approved_option_lifecycle_predecessors`
- `approved_option_lifecycle_source_legs`
- `pnl_calculation_runs`
- `pnl_group_results`
- `pnl_closed_lot_allocations`
- `pnl_lifecycle_allocations`
- `normalized_fill_revisions`
- `journal_entries`
- `journal_entry_revisions`
- `journal_reviews`
- `journal_strategies`
- `journal_tags`
- `journal_entry_tag_events`
- `journal_attachments` (metadata schema only; writes disabled by policy)
- `journal_saved_views`
- `journal_goals`
- `journal_goal_checkins`
- `journal_habits`
- `journal_habit_events`
- `journal_review_period_events`
- `schema_migrations`
- `broker_position_snapshot_runs`
- `broker_position_snapshot_records`
- `pnl_position_valuation_runs`
- `pnl_canonical_position_valuations`
- `pnl_bounded_valuation_runs`
- `pnl_bounded_position_valuations`
- `pnl_bounded_valuation_subtotals`
- `pnl_broker_current_valuation_runs`
- `pnl_broker_current_position_valuations`
- `pnl_broker_current_portfolio_totals`

The baseline is now versioned at `0001_establish_schema_version`.

Roadmap item JRN-01 now enforces bootstrap validation and migration
ledger recording on the temporary-copy path before any production database
upgrade approval.

## Storage and naming

Migration artifacts live under:

```text
scripts/journal/migrations/
```

Use one monotonically increasing four-digit version per logical change:

```text
NNNN_short_kebab_description.sql
```

Examples:

```text
0001_establish_schema_version.sql
0002_add_normalized_accounts_orders_positions_transactions.sql
0003_add_normalized_fill_revisions.sql
0004_add_normalized_lifecycle_events.sql
0005_add_durable_journal_domain.sql
0006_add_journal_saved_views.sql
0007_add_journal_goals_habits_reviews.sql
0008_add_lifecycle_event_legs.sql
0009_add_utc_financial_event_instants.sql
0010_add_approved_lifecycle_pnl_allocations.sql
0011_add_normalized_market_quotes.sql
0012_add_quote_capture_envelope.sql
0013_add_canonical_position_valuations.sql
0014_add_bounded_pnl03_valuations.sql
0015_add_broker_current_position_valuations.sql
```

Migration 0009 adds explicit canonical UTC evidence fields without
reinterpreting older timezone-less values. Migration 0010 keeps reviewed
lifecycle instructions separate from normalized broker evidence and adds
append-only, fingerprinted P&L runs and allocation lineage. Neither migration
has been applied to the live journal database by this implementation work.

Migration 0009's header historically called ADR-0003 accepted before the seven
owner confirmations were recorded, and migration 0010 repeats that dependency
wording. Released migrations are checksum-locked and were not edited. The
current ADR and architecture register are authoritative and record the later
explicit acceptance date.

Migration 0011 adds provider/connection-scoped quote ingestion runs and
normalized top-of-book quote evidence. Freshness remains a read-time
calculation rather than a stored permanent label. Migration 0011 has also not
been applied to the live journal database.

Migration 0012 additively binds new quote-ingestion runs to a versioned,
provider-neutral capture envelope: exact request scope, receive time,
checksum-backed source locator, and full-envelope replay fingerprint. Existing
migration-0011 rows remain legacy evidence. Migration 0012 has not been applied
to a live journal database.

Migration 0013 additively introduces PNL-03 broker-position snapshot and
canonical valuation result tables. It does not copy or reinterpret legacy
`normalized_positions`. Repository validation uses temporary DuckDB databases
only; applying 0013 to an actual journal remains separately approval-gated.

Migration 0014 separately persists the bounded ADR-0022 route rather than
forcing route, binding, assembly, complete-scope, and eligible-subtotal meaning
into the generic 0013 tables. Its repository requires an existing migrated
database, validates exact snapshot identity and quantity scope, writes
transactionally, accepts only an identical replay, and reads one explicitly
named run without a latest-run fallback. Validation remains limited to
temporary DuckDB databases; applying 0014 to an actual journal remains a
separate approval gate.

Migration 0015 additively preserves the direction-specific broker tax-lot
average on snapshot records and persists the separate ADR-0023 broker-current
run, position, currency-quantum, metric-availability, reconciliation, and
complete-total lineage. The repository requires an existing migrated database,
rebuilds the run from the supplied snapshot before writing, accepts only an
identical replay, and reads one explicitly named run. Validation uses temporary
DuckDB databases only; applying 0015 to an actual journal remains a separate
approval gate. Existing generic and bounded snapshot writers retain explicit
0013/0014 compatibility and populate the added tax-lot field whenever 0015 is
present. A pre-0015 snapshot row lacking that field cannot be silently upgraded
into broker-current authority; it must fail closed and be re-materialized under
versioned evidence.

Rules:

- A version number is unique and never reused.
- Applied migration files are immutable. Correct a defect with a new migration.
- SQL is the default format.
- A data transformation that cannot be expressed safely in SQL requires a
  same-version Python companion and explicit runner support; it must not be run
  manually.
- Migrations must not contain credentials, private data, account identifiers,
  machine-specific paths, or generated output.

## Migration ledger

JRN-01 must add a migration ledger owned by the migration runner. At minimum it
must record:

- version
- migration name
- immutable file checksum
- applied timestamp
- application version or Git revision
- migration run ID
- final status

The runner must fail closed when:

- an applied checksum differs from the repository file
- versions are duplicated or applied out of order
- the database is newer than the application supports
- the actual pre-migration schema does not match the migration's expectation
- backup, transaction, migration, or post-validation fails

An `IF NOT EXISTS` clause must not be used to conceal unexpected schema drift.
Idempotency comes from the migration ledger and explicit preconditions.

## Required migration content

Each migration must document:

- purpose and related contract or ADR
- expected starting version and schema
- tables, columns, indexes, constraints, and data affected
- producer and consumer impact
- forward transformation
- validation queries and expected results
- failure behavior
- backup restoration or forward-correction plan

Breaking changes require compatibility handling, producer/consumer updates,
examples, and contract tests in the same controlled change.

## Safe execution workflow

### 1. Read-only discovery

Before implementation:

- inspect schema, DuckDB version, file size, row counts, constraints, indexes,
  representative private-safe data, and integrity checks
- identify every reader, writer, payload, report, and operator command
- produce an impact map and define expected results

### 2. Backup and restoration plan

- close or block all writers
- create a timestamped database backup outside the live database path
- record source and backup checksums and sizes
- define the exact restoration procedure
- test restoration when risk warrants it

A backup is not considered valid merely because a copy command succeeded.

### 3. Temporary-copy rehearsal

- copy the realistic source database to an isolated temporary location
- run the migration only on that copy
- run schema, row-count, duplicate, lineage, contract, import, payload, and
  application tests
- rehearse failure and restoration behavior
- prove repeat invocation does not reapply or corrupt the migration

### 4. Explicit production apply

Applying a migration to the live journal requires explicit approval. The runner
must display:

- database path and current/target version
- migration versions and checksums
- backup path
- expected schema/data effects
- validation plan and rollback method

The operation must use an exclusive single-writer boundary. Each migration must
run in one DuckDB transaction wherever DuckDB supports the required statements.
A failure must roll back and stop later migrations.

### 5. Post-migration validation

Validate:

- migration-ledger record and checksum
- expected schema, constraints, and indexes
- preserved row counts and identifiers unless an approved transformation says
  otherwise
- no orphaned lineage, duplicate identities, or lost manual reviews
- import, reconciliation, payload, and application contracts
- database reopen and read-only health checks
- Git and runtime paths contain no backup or database artifact

## Rollback policy

OneJournal does not use automatic destructive down migrations.

Rollback means:

- restore the verified pre-migration database backup when the new database
  cannot be trusted, or
- apply a separately reviewed forward corrective migration when preserving
  post-migration writes is required

Never drop columns, truncate tables, reinterpret stored values, or overwrite the
live journal silently. Restoring a backup must account for any writes made after
the backup; those writes must not be discarded without explicit approval and a
reconciliation plan.

## Bootstrap consistency

After JRN-01 establishes versioning, creating a new database and migrating an
existing baseline database must produce equivalent current schemas.

`init_journal_db.py` must not evolve independently from the migration history.
The future bootstrap path should create the minimal approved baseline and apply
the same ordered migrations used for existing databases.

## Validation requirements

Every migration change requires the smallest relevant combination of:

- migration tests on empty and realistic populated temporary databases
- precondition and drift-failure tests
- checksum and ordering tests
- transaction rollback and repeat-run tests
- data preservation and reconciliation tests
- producer, consumer, payload, and UI regression tests
- backup restoration evidence

Migration success must never be inferred only from a zero process exit code.
