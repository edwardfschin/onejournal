# OneJournal Schwab Historical Raw Fetch Operator

## Purpose

This is D2.3: the sequential operator that executes an approved D2.2 history
plan. It uses the existing OneJournal-scoped Schwab transport and saves only
raw orders and transactions JSON under `data/raw/schwab`. Account, order, and
transaction history requests use GET; an expired existing token may require an
OAuth refresh POST that updates only the private OneJournal token. It does not
normalize fills, write DuckDB, rebuild dashboard payloads, or place, modify,
replace, or cancel broker orders.

The operator accepts only `ONEJOURNAL_SCHWAB_*` configuration and a token below
`~/.onejournal/` by default. Generic configuration names and any token path
below `~/.onebot/` fail before dry-run, token, network, raw-evidence, or report
activity.

## Required sequence

1. Review the D2.2 planner output and choose the history start date.
2. Run this operator in `--dry-run` mode.
3. Run and validate a small live batch outside the protected time.
4. Review the raw files and operator report.
5. Only then approve a full historical run.

## Dry run

```bash
python scripts/journal/fetch_schwab_raw_history_backfill.py \
  --start 2025-11-01 \
  --end 2025-11-30 \
  --dry-run
```

Dry run accesses no token, makes no network call, and writes neither raw JSON
nor an operator report.

## Live operator

Run only outside the protected interval:

```bash
python scripts/journal/fetch_schwab_raw_history_backfill.py \
  --start 2025-11-01 \
  --end 2025-11-30 \
  --chunk-days 30
```

The default `--fetch-date` is today in Asia/Singapore. Use the same explicit
`--fetch-date` when resuming a stopped run so completed raw pairs are found.

## Safety and resume behaviour

- Protected time is 19:50 through 20:29:59 SGT. A live invocation in that
  interval fails before token or network access; dry-run remains safe.
- One non-blocking token lock prevents two D2.3 operators from refreshing the
  same token in parallel.
- Windows run sequentially. Each uses at most one orders GET and one
  transactions GET.
- A complete existing orders/transactions pair is skipped on rerun.
- For a partial pair left by a prior interrupted run, only the missing raw
  evidence is fetched; existing raw JSON is never overwritten.
- A live run writes a CSV report to
  `output/reports/schwab_raw_history_backfill/`. This is audit metadata, not
  journal data. The raw broker evidence remains JSON only.

## Operator report

The report records each window, paths, whether each raw side was fetched or
reused, status (`fetched`, `resumed_partial`, `skipped_complete`, or `failed`),
and a bounded failure message. If a fetch fails, rerun the same command: all
completed pairs are skipped and the first incomplete window is retried.

## Do not continue automatically

Completion of D2.3 does not authorize the full historical fetch. Validate a
small live batch and its report first, then make a separate approval decision.
