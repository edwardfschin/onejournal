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
- Adapter contract: deterministic Schwab orders JSON normalization.
- Integration: schema initialization, import, review merge, DuckDB reads, and
  DB dashboard payload construction using a temporary database.
- Regression: invalid inputs, as-of mismatches, duplicate payload entries, and
  unsupported fill sides must fail explicitly.

Tests must not use the production journal database, private broker data, broker
APIs, or order APIs.

## Run

From the repository root with the OneJournal environment active:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The full baseline also runs this suite:

```bash
./bin/onejournal_check.sh
```

The clean-checkout CI entry point also runs this suite together with dependency,
compilation, repository-safety, and fixture contract checks:

```bash
./bin/onejournal_ci.sh
```
