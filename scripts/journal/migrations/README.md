# OneJournal Journal Migrations

This directory is reserved for ordered DuckDB migration artifacts governed by
`docs/database_migrations.md`.

There are currently one baseline migration file:

- `0001_establish_schema_version.sql`:
  create the migration ledger (`schema_migrations`) with run metadata and audit
  fields.

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
