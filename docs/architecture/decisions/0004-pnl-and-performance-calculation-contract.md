# ADR-0004: Define P&L, cost-basis, and performance calculation semantics

- Status: Proposed
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-03, PNL-01 through PNL-08
- Related contracts: ADR-0003, `docs/onejournal_data_contract_v1.md`,
  `docs/normalized_fills_odfs_contract.md`
- Supersedes: None
- Superseded by: None

## Context

The current journal groups normalized fills into intentionally simple episode
previews. It calculates `gross_cashflow`, commissions, fees, and net quantity,
but it does not calculate cost basis, realized P&L, unrealized P&L, positions,
marks, returns, or tax lots. A cash credit is therefore not a profit, and an
open premium is not realized P&L.

The initial product scope covers US stocks and listed equity options. ADR-0003
is proposed to require USD reporting, decimal arithmetic, New York market
dates, and explicit FX evidence. This P&L contract cannot be implemented or
published until ADR-0003 is accepted and its required data corrections are
complete.

## Decision

Subject to ADR-0003 and project-owner approval, OneJournal will calculate
financial results as follows.

- Confirmed fills and approved non-trade lifecycle events are the only basis
  for cost basis and realized P&L. Orders, signals, broker estimates, and raw
  cashflow labels are not substitutes.
- Each account, instrument, currency, and position direction has its own
  ordered tax-lot inventory. The initial matching method is FIFO. A later
  approved election may add specific-lot support; it must not silently change
  historical results.
- A closing fill realizes P&L only for the quantity matched against existing
  open lots. A partial close realizes only its allocated quantity; its remaining
  open quantity retains its allocated cost basis.
- For a long lot, realized P&L is closing proceeds less allocated opening cost,
  commissions, and fees. For a short lot, it is opening proceeds less closing
  cost, commissions, and fees. Equity-option amounts use the broker-confirmed
  contract multiplier and include all allocated costs.
- Commissions and fees are allocated to the related fill or lifecycle event at
  ingestion. When a broker supplies only an order-level amount, the allocation
  method, residual, and source must be recorded and reconcile exactly. No fee
  may disappear into a summary total.
- Unrealized P&L is an open-lot calculation only: current mark value less open
  cost basis, including allocated opening costs and any approved closing-cost
  estimate. Without an approved, fresh, instrument-appropriate mark, it is
  unavailable, not zero.
- Total P&L equals realized P&L plus unrealized P&L only when both are valid,
  in the same currency, and share a stated as-of instant. Otherwise it is
  unavailable or incomplete.
- Gross cashflow, net cashflow, realized P&L, unrealized P&L, total P&L, cost
  basis, market value, commissions, and fees are distinct labelled fields.
- Returns are unavailable until a denominator policy is approved. The initial
  implementation may show dollar P&L only; it must not label a cashflow-based
  percentage as a return.

### Worked examples

| Event | Calculation | Result |
|---|---|---|
| Buy 100 shares at $10, $1 fee; sell 100 at $12, $1 fee | proceeds $1,200 - close fee $1 - opening cost $1,000 - open fee $1 | realized P&L $198 |
| Buy 100 shares at $10; sell 40 at $12 | matched proceeds $480 - matched cost $400 | realized P&L $80; 60 shares retain $600 cost basis before allocated fees |
| Sell one option at $2.00 with 100 multiplier; buy to close at $1.20; total fees $2 | $200 opening proceeds - $120 close cost - $2 fees | realized P&L $78 |
| Open 100 shares at $10; approved fresh mark $11 | market value $1,100 - cost basis $1,000 | unrealized P&L $100 before allocated fees |

All examples use USD and decimal arithmetic. A non-USD result without the
approved FX evidence in ADR-0003 remains native-currency only.

## Boundaries

This decision does not define tax reporting, tax jurisdiction, wash-sale
treatment, dividends, assignments, exercises, expirations, corporate actions,
FX rate timing, market-data provider, or performance-return denominator. Those
need separate lifecycle, market-data, and return-policy decisions.

Broker-reported P&L is reconciliation evidence, not an override of the
canonical calculation without an approved discrepancy workflow.

## Alternatives considered

### Average-cost matching

This is simple for a position view but obscures the chronological lot evidence
needed for journaling and is not the preferred initial method for option and
partial-exit lifecycle review. Rejected for the initial canonical calculation.

### Use broker reported P&L as canonical

This is convenient but hides methodology, may vary by broker, and cannot
provide consistent multi-broker traceability. Rejected.

### Call net cashflow realized P&L

This misstates open positions and premium strategies. Rejected.

## Consequences

### Positive

- Every published P&L value is explainable from lots, fills, fees, and marks.
- Partial exits and options preserve quantity and multiplier correctness.
- Broker-specific results can be reconciled without becoming domain logic.

### Negative and trade-offs

- A durable lot/allocation ledger and focused calculation tests are required.
- FIFO may differ from a broker's tax or display choice; differences must be
  shown as reconciliation differences, not silently hidden.
- Marks, stale-data rules, and return metrics remain unavailable until their
  own evidence and contracts exist.

## Compatibility and migration

Existing `gross_cashflow` is a preview field and must not be renamed or
reinterpreted as P&L. New versioned calculation outputs need calculation
version, lot allocation lineage, source fill/event IDs, currency, as-of
instant, and completeness status. Historical results must be reproducible from
the retained event set and calculation version.

## Security, privacy, and financial impact

Incorrect P&L can cause harmful trading and reporting decisions. Results must
fail closed for incomplete fills, unresolved lifecycle events, missing
multipliers, missing currency/FX, or stale/missing marks. No P&L feature
authorizes broker writes or automated trading.

## Validation

Implementation must include exact unit and integration cases for long and short
stocks, long and short options, partial fills/exits, multi-leg fee allocation,
commissions, multipliers, zero/negative/unknown marks, FIFO ordering, currency
gates, and reconciliation to source evidence. Each example must reconcile to
the cent at the approved boundary.

## Rollback or supersession

This proposal changes no calculations. Accepted implementation must version
results so a corrected algorithm can be recomputed beside—not silently over—an
earlier version. A later approved lot or return policy supersedes this ADR with
historical comparison and migration rules.
