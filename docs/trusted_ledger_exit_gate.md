# Trusted Ledger Exit Gate

## Purpose

This document defines a bounded, binary evidence gate for one real,
broker-confirmed closed trade lifecycle. It tests whether OneJournal can retain
the relevant evidence, represent the lifecycle, calculate its result,
reconcile that result, and explain it without guessing or hiding a discrepancy.

This is the real-lifecycle evidence gate for `PNL-01` in the
[product roadmap](onejournal_product_roadmap.md). It does not change a roadmap
status or create an acceptance decision by itself.

## Gate scope

One gate assessment covers exactly one identified lifecycle, including its:

- broker, account, instrument, and strategy scope;
- opening, adjustment, lifecycle-event, and closing evidence where applicable;
- source and import identities;
- calculation version and exact input set;
- reconciliation result; and
- recorded limitations and acceptance decision.

The assessed lifecycle must be real broker evidence. Synthetic fixtures,
description-only lifecycle hints, or records still marked `review_required` may
support testing or investigation, but they cannot satisfy this gate.

## Prerequisites

Before the gate can pass:

1. The lifecycle is closed and its economic classification is explicitly
   reviewed and approved.
2. The applicable P&L policy in
   [ADR-0004](architecture/decisions/0004-pnl-and-performance-calculation-contract.md)
   is accepted and applies to the case.
3. The seven owner decisions blocking `CON-02` are resolved and
   [ADR-0003](architecture/decisions/0003-financial-units-and-time-contract.md)
   is accepted. Evidence may be assembled earlier, but financial acceptance
   cannot bypass unresolved currency, precision, rounding, time, market-date,
   display-timezone, or calendar/session policy.
4. No material source, normalization, lifecycle, calculation, or reconciliation
   discrepancy remains unresolved.

## Required evidence

| Requirement | Passing evidence |
|---|---|
| Retained broker evidence | The exact broker evidence used for the assessment is retained without in-place alteration, privately stored, and identified by source, account scope, retrieval or statement period, and retained-file identity. |
| Normalized records | Every in-scope normalized record is identified and traceable to its import run and retained source evidence under the applicable data contract. |
| Approved lifecycle classification | The episode, event types, legs, predecessor links, and close state are explicitly reviewed; description-only hints and unresolved `review_required` records are excluded from financial totals. |
| Exact calculation inputs | The evidence records every input used, including stable record identities, calculation-input fingerprint, signed quantities, multipliers, prices or cash amounts, commissions, fees, currencies, timestamps, and approved lifecycle-event instructions. |
| Deterministic result | The calculation version and output are recorded, repeatable from the same approved inputs, and explainable from source evidence through normalized records and lifecycle allocations. |
| Broker reconciliation | Quantities, cash movements, commissions, fees, and the resulting realized P&L reconcile to broker evidence under the approved tolerance and classification rules. |
| Limitations | Missing evidence, unsupported events, manual judgments, bounded assumptions, environment, account, instrument, and date scope are recorded explicitly. |
| Owner sign-off | The project owner records the lifecycle identity, evidence locations, validation result, remaining limitations, decision, decision date, and accepted scope. |

The bounded identity and calculation-input fingerprint foundation in
[ADR-0006](architecture/decisions/0006-record-identity-lineage-and-correction-contract.md)
may support the evidence. It must not be represented as the complete provenance
and correction capability proposed by
[ADR-0010](architecture/decisions/0010-complete-evidence-provenance-and-correction-governance.md).

## Decision rule

The gate result is either `PASS` or `FAIL`:

- `PASS` requires every prerequisite and required-evidence row to be satisfied,
  no unresolved material discrepancy, and explicit owner sign-off for the
  stated lifecycle scope.
- `FAIL` applies when any required evidence is missing, ambiguous, inferred,
  unreconciled, or outside approved policy. The failure reason and evidence gap
  must be recorded; an incomplete result must not be promoted as a partial pass.

A later correction, superseding broker record, calculation-version change, or
new discrepancy invalidates the prior pass for decision use until the lifecycle
is reassessed. History must be preserved; the earlier assessment is not
rewritten.

## Minimum assessment record

Record at least:

- gate result and assessment date;
- lifecycle, broker, account, instrument, and bounded date scope;
- retained source-evidence identities and import-run identities;
- normalized record, episode, event-leg, predecessor, and allocation identities;
- calculation version, exact input fingerprint, and output identity;
- quantity, multiplier, price or cash, commission, fee, currency, and realized
  P&L reconciliation results;
- every exclusion, limitation, manual judgment, and unresolved gap; and
- owner, decision date, decision, and explicitly accepted scope.

The assessment record is audit evidence. It is not an instruction to modify raw
broker evidence, a runtime database, migration history, or generated output.

## Explicit exclusions

Passing this gate does **not** establish:

- portfolio-wide, account-wide, broker-wide, strategy-wide, or sustained
  financial correctness;
- acceptance of any lifecycle, event type, instrument, currency, or period not
  included in the assessment;
- canonical current positions, unrealized P&L, market-data valuation,
  performance reporting, or downstream `PNL-02` through `PNL-08` capability;
- production readiness, runtime migration, deployment, resilience, security,
  privacy, operational acceptance, or general financial acceptance;
- complete raw-to-output provenance, normalized-record versioning,
  supersession, governed correction, downstream invalidation, recalculation,
  retention, or recovery under proposed ADR-0010; or
- authorization for broker/provider access, a live provider call, database or
  migration changes, provider configuration, deployment, commit, push, paper
  trading, or live trading.

`PNL-01` proves lifecycle evidence and realized-P&L reconciliation within this
bounded gate. `PNL-02` separately proves the market-data contract and provider
adapter. Progress in one lane does not satisfy the other, and dependent
portfolio valuation must not bypass either gate.
