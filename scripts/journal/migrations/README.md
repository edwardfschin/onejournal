# OneJournal Journal Migrations

This directory is reserved for ordered DuckDB migration artifacts governed by
`docs/database_migrations.md`.

There are currently no migration files. The existing DuckDB schema is an
unversioned bootstrap baseline created by `scripts/journal/init_journal_db.py`.
JRN-01 will establish the migration ledger and first inspected baseline without
experimenting on the runtime journal database.

Do not add or execute a migration without:

- complete producer, consumer, schema, and data-flow understanding
- an impact map
- temporary-copy rehearsal
- backup and restoration planning
- proportional automated validation
- explicit approval before applying it to the live journal
