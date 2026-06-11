# OneJournal Episode Quality Contract

## Purpose

This contract protects the quality of trade episodes shown in the OneJournal dashboard.

The dashboard should show useful journal objects, not raw grouped fills.

## Required episode fields

Each recent trade episode must have episode_uid, primary_symbol, strategy_label, status, leg_count, legs, leg_summary, gross_cashflow, commission, and fees.

## Primary symbol rule

primary_symbol must be the tradable underlying symbol.

Correct examples:

- episode_uid: manual_csv:DEMO_ACCOUNT:option:AAPL_SELL_PUT_001; primary_symbol: AAPL
- episode_uid: manual_csv:DEMO_ACCOUNT:option:SPY_PUT_VERTICAL_001; primary_symbol: SPY
- episode_uid: manual_csv:DEMO_ACCOUNT:stock:TSLA_STOCK_SHORT_001; primary_symbol: TSLA

Incorrect examples:

- primary_symbol: AAPL_SELL_PUT_001
- primary_symbol: SPY_PUT_VERTICAL_001
- primary_symbol: TSLA_STOCK_SHORT_001

episode_uid remains the stable identity. primary_symbol is for operator display, filtering, and future reporting.

## Strategy rule

Known examples should not be labelled Unknown.

Acceptable examples include Sell Put, Buy Call, Put Credit Vertical, Put Debit Vertical, Call Credit Vertical, Call Debit Vertical, Stock Long, and Stock Short.

## Leg rule

leg_count must match the number of items in legs.

## Safety

This contract is read-only. It does not call broker APIs, place orders, cancel orders, modify orders, or auto-trade.

## Validation

Run:

python scripts/journal/check_episode_quality_contract.py --payload output/dashboard/latest/dashboard_payload_from_db.json
