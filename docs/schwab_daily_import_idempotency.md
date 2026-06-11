# OneJournal Schwab Daily Import Idempotency Guard

## Purpose

This guard proves that rerunning the same Schwab daily import does not duplicate fills, trade episodes, episode legs, or manual review rows.

## Command

python scripts/journal/check_schwab_daily_import_idempotency.py --asof 2025-05-19 --orders data/raw/schwab/YYYY-MM-DD/orders_all/file.json --transactions data/raw/schwab/YYYY-MM-DD/transactions/file.json

## Safety

The guard copies the DuckDB file to a temporary DB and runs the import twice on the copy.

It does not mutate the real DuckDB file.

It does not call Schwab REST APIs.

It does not place, cancel, replace, or modify orders.

## Pass condition

The second import must not increase normalized_fills, trade_episodes, or trade_episode_legs.

The duplicate source_fill_id, duplicate episode_uid, and duplicate review episode_uid counts must remain zero.
