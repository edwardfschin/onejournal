# OneJournal Automated Tests

## Purpose

The initial test suite locks the behavior that is implemented and validated
today. It does not imply that preview trade grouping is the final lifecycle or
that gross cashflow is P&L.

The suite uses Python's standard-library `unittest` runner to keep the early
foundation simple and dependency-free.

## Test layers

- Unit: manual CSV parsing, episode grouping/classification, and dashboard
  payload construction.
- Lifecycle contract: partial fill events and partial close behavior.
- Financial contract: versioned FIFO closed-lot allocations, source-fill
  lineage, quantities, multipliers, commission/fee allocation, realized P&L,
  open cost basis, marks, and fail-closed incomplete evidence.
- Adapter contract: deterministic Schwab orders JSON normalization.
- Integration: schema initialization and migration, import, append-only journal
  history, review compatibility projection, replay preservation, DuckDB reads,
  and DB dashboard payload construction using a temporary database.
- Regression: invalid inputs, as-of mismatches, duplicate payload entries, and
  unsupported fill sides must fail explicitly.
- Journal product: deterministic review queues, private structured entry
  history, search/filter/saved-view behavior, attachment fail-closed policy,
  process goals, habits, and explicit-period recurring review transitions.

Tests must not use the production journal database, private broker data, broker
APIs, or order APIs.

## Run

From the repository root with `PYTHONPATH=.:src` (or via `./bin/onejournal_ci.sh`):

```bash
PYTHONPATH=.:src python3 -m unittest discover -s tests -p "test_*.py" -v
```

The full baseline also runs this suite:

```bash
./bin/onejournal_ci.sh
```

The clean-checkout CI entry point also runs this suite together with dependency,
compilation, repository-safety, and fixture contract checks:

```bash
./bin/onejournal_ci.sh
```
