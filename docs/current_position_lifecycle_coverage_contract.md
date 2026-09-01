# Current-position lifecycle coverage contract

## Purpose

`onejournal.current-position-lifecycle-coverage.v1` is the credential-free,
provider-independent PNL-03N boundary between verified lifecycle windows and a
future canonical current position. It assembles already converted order,
transaction, and lifecycle evidence in memory and assesses whether each exact
broker position has enough fill history to proceed.

It does not call a provider, use credentials, read or write files, create a
private mapping, write DuckDB, calculate accepted cost basis or P&L, select a
valuation mark, publish a payload, or approve a position.

## Inputs and scope

The boundary accepts:

- one or more already verified `ConvertedExternalLifecycleEvidence` windows;
- one exact private provider instrument identifier, asset class, and non-zero
  broker quantity for every current position in the complete snapshot; and
- the snapshot retrieval instant as the evaluation cutoff.

All windows must share one provider, connection, and opaque account. Windows
are sorted chronologically and must be contiguous and non-overlapping. The
evaluation date must fall within the assembled range. A gap, overlap, mixed
account, duplicate target, malformed decimal/time, or conflicting replay fails
the entire assembly.

## Assembly and reconciliation

Order fills, transaction fills, lifecycle events, and event legs use their
stable source identities. Exact replays deduplicate; the same stable identity
with different normalized content fails closed. Each source window already
admits fills by exact execution time and lifecycle events/legs by exact event
time. The assembler preserves and reports those source-window exclusion counts
separately, including valid non-intersecting raw order records excluded before
normalization. Rows after the broker snapshot cutoff are also excluded and
counted so later activity cannot alter an earlier position.

Order and transaction fills reconcile across the complete assembled set using
exact date, provider order reference, asset class, instrument identity, side,
quantity, price, and option multiplier. This permits an order entered in one
window and completed in a later transaction window to match without weakening
the key.

Transaction rows remain accounting authority for currency, fees, multiplier,
and canonical instrument terms. Order rows remain independent execution
evidence. The assembler never substitutes an order adapter's implicit currency
for transaction evidence.

## Per-position states

The signed transaction quantity is compared with the complete broker snapshot
quantity for the same provider instrument:

- `fill_flat_start_proven`: accepted normalized transaction fills net exactly
  to the broker quantity, all applicable order rows reconcile, and no captured
  lifecycle leg affects the position. Algebraically, the position at the start
  of the assembled interval is zero for this fill scope.
- `history_extension_required`: no transaction fill exists or the fill net
  differs from the broker quantity. Earlier contiguous evidence is required.
- `review_required`: execution/accounting evidence is unmatched or captured
  lifecycle evidence affects the position. It cannot enter FIFO, valuation, or
  a financial total.

A transaction lacking a provider order ID is specifically
`transaction_order_id_missing`; it is not matched by symbol, time, price, or
quantity. A transaction with an order ID but no assembled order evidence is
`transaction_order_evidence_missing`. An order without transaction accounting
evidence is `transaction_accounting_evidence_missing`. Targeted lifecycle legs
and unscoped review-required lifecycle markers remain explicit blockers.

`fill_flat_start_proven` is a bounded fill-coverage result, not PNL-03 financial
acceptance. A canonical position still requires durable private instrument
binding, accepted lifecycle conversion, FIFO calculation, exact broker
reconciliation, a valid valuation mark, persistence/migration approval, and
owner acceptance.

## Privacy-safe audit

The audit includes only the contract and assembly digests, opaque connection,
window and evaluation times, row/reconciliation counts, position status/reason
counts, exact source-window and post-evaluation exclusion counts,
deduplication counts, and an explicit unmaterialized status.
It emits no provider symbols, account identifiers, quantities, prices, raw
payloads, private paths, or credentials.

## Validation and rollback

Offline tests cover cross-window matching, deterministic replay, duplicate and
conflict behavior, gaps, overlaps, account mismatch, missing provider order
IDs, earlier-history requirements, lifecycle review, post-snapshot exclusion,
source-window exclusion accounting, option identity conflict, and privacy-safe
output.

Rollback removes the additive module, exports, tests, and this contract. No
private evidence or database state is created or changed.
