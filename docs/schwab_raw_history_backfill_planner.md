# OneJournal Schwab Raw History Backfill Planner

## Purpose

This is the D2.2 planning step for a future Schwab historical raw-fetch run.
It converts an inclusive history range into sequential calendar windows before
any live broker operation is approved.

The planner is deliberately offline. It does not import the Schwab fetcher and
does not access the network, tokens, raw evidence, DuckDB, or output folders.
It makes no broker order action.

## Command

```bash
python scripts/journal/plan_schwab_raw_history_backfill.py \
  --start 2020-01-01 \
  --end 2026-06-11 \
  --chunk-days 30
```

`--chunk-days` is the maximum number of inclusive calendar days in each
window. Its default is 30. The final window is shortened when necessary.

## Output and API estimate

The planner prints every proposed window and two future GET totals:

- `ESTIMATED_GETS_WITH_HASH` is two GETs per window: one orders request and
  one transactions request.
- `ESTIMATED_GETS_WITH_DISCOVERY` also includes one account-number lookup to
  discover the account hash once for the complete sequential run.

The latter is an estimate for the future operator when it does not already
have an approved account hash. The planner itself makes neither request.

For the command above, the expected review values are:

```text
WINDOWS_TOTAL                : 79
ESTIMATED_GETS_WITH_HASH     : 158
ESTIMATED_GETS_WITH_DISCOVERY: 159
```

## Safety contract

Every successful plan must report:

```text
NETWORK_ACCESS               : disabled
TOKEN_ACCESS                 : disabled
FILESYSTEM_WRITE              : disabled
DUCKDB_WRITE                  : disabled
BROKER_ORDER_WRITE            : disabled
```

The plan is not authorization to fetch history. Review the selected start
date, window count, and estimated GET count first. D2.3 must add a separate,
sequential, resumable live raw-fetch operator with dry-run and protected-time
controls. Raw JSON remains the only permitted output of that future operator.
