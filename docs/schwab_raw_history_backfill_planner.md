# OneJournal Schwab Raw History Acquisition-Request Planner

## Purpose

This credential-free planner converts an inclusive history range into
sequential calendar windows for review as a possible temporary external-
producer request or future OneJournal provider-connector request. It does not
select a token owner, create an executable fetch plan, or authorize a broker
operation.

The planner is deliberately offline. OneJournal contains no active Schwab
history fetcher. The planner does not access the network, tokens, raw evidence,
DuckDB, or output folders, and it makes no broker order action.

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

The planner prints every proposed window and two indicative GET totals for a
separately approved provider connector or temporary evidence producer:

- `ESTIMATED_GETS_WITH_HASH` is two GETs per window: one orders request and
  one transactions request.
- `ESTIMATED_GETS_WITH_DISCOVERY` also includes one account-number lookup to
  discover the account hash once for the complete sequential run.

The latter is an estimate for an approved producer when it does not already
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
TOKEN_OWNER                  : not assigned by this plan
EXECUTION_OWNER              : separate provider acquisition approval
BROKER_REQUEST_AUTHORITY     : none
NETWORK_ACCESS               : disabled
TOKEN_ACCESS                 : disabled
FILESYSTEM_WRITE              : disabled
DUCKDB_WRITE                  : disabled
BROKER_ORDER_WRITE            : disabled
```

The plan is not authorization to fetch history. Review the exact evidence gap,
selected dates, window count, and indicative GET count first. If historical
evidence is genuinely required, define and separately approve the smallest
case-specific provider acquisition, private evidence boundary, and OneJournal
validation/import path. Before the target provider plane exists, any temporary
external producer is a bounded bridge only. In the target architecture, an
isolated OneJournal provider connector owns acquisition while the journal and
financial layers remain provider-independent. Do not recreate the retired ad
hoc live history scripts.
