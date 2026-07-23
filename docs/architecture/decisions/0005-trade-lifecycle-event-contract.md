# ADR-0005: Define trade lifecycle event treatment

- Status: Proposed
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-04, JRN-02 through JRN-05, PNL-01 through PNL-08
- Related contracts: ADR-0003, ADR-0004, `docs/normalized_fills_odfs_contract.md`
- Supersedes: None
- Superseded by: None

## Context

Current trade episodes group fills by broker, account, asset class, and a
symbol or optional user-supplied group ID. The implementation documents that it
is not a final lifecycle engine and does not safely model rolls, partial exits,
assignments, exercises, expirations, adjustments, or corporate actions.

Lifecycle events determine open lots, cost basis, realized P&L, position
quantity, and journal narrative. Treating them as ordinary fills or silently
discarding them would create incorrect financial results.

## Decision

Subject to ADR-0003 and ADR-0004 approval, OneJournal will use an immutable,
typed lifecycle-event ledger. A lifecycle event links to its broker evidence,
source record, effective instant, market date, account, instrument, currency,
and affected lots. It may create allocation records; it does not rewrite prior
economic events.

- Partial fills are separate confirmed fill events. A parent order does not
  replace its fills.
- Partial exits close only matched FIFO lot quantity and retain the remainder as
  open inventory.
- A multi-leg order is an execution grouping, not proof of one economic trade.
  Legs remain independently identifiable; a strategy/episode link is explicit
  and may be revised without changing fills.
- A roll is two linked economic actions: close the prior position and open the
  replacement position. It is not a single fill, a continuous unchanged lot,
  or an automatic realization deferral.
- Assignment and exercise are broker-confirmed lifecycle events that close or
  transform the option lot and create the resulting equity lot/cash movement
  under an explicit conversion link. They require source evidence and contract
  multiplier verification.
- Expiration is a broker-confirmed lifecycle event. A worthless long option
  closes at zero proceeds; an expiring short option closes at zero cost only
  when broker evidence confirms no assignment/exercise. Otherwise results are
  pending reconciliation.
- Dividends, interest, transfers, deposits, withdrawals, and cash adjustments
  are typed cash events. They are not trade P&L by default and must not alter a
  security lot unless an approved event rule says so.
- Splits, mergers, spin-offs, symbol changes, deliverable changes, and other
  corporate actions require a broker/evidence-backed transformation event that
  preserves predecessor/successor lot lineage. Unsupported actions make
  affected positions and P&L unavailable or reconciliation-pending.
- Corrections and cancellations create linked corrective events; historical
  source events remain auditable. No lifecycle event is inferred merely from a
  description string when structured broker evidence is absent.

## Boundaries

This decision defines event semantics, not the tax-lot formula, data-provider
choice, tax treatment, or execution behavior. It does not authorize importing
legacy execution code, sending orders, or parsing unknown broker records into
plausible lifecycle events.

## Alternatives considered

### One mutable trade row per idea

It is easy to display but loses partial fill, adjustment, and broker lineage.
Rejected.

### Infer lifecycle events from descriptions alone

This can fill gaps but is unreliable for financial correctness. Rejected as a
canonical source; it may produce a review suggestion labelled unconfirmed.

### Treat rolls as a single uninterrupted position

This conceals the close/open economics and corrupts lot and P&L history.
Rejected.

## Consequences

### Positive

- Exceptional broker activity remains traceable instead of becoming a manual
  patch or unexplained discrepancy.
- Journal episodes can tell a coherent story while financial calculations use
  immutable event evidence.
- Unsupported events fail closed rather than contaminating portfolio totals.

### Negative and trade-offs

- The journal needs new event, lot-link, and episode-link schemas plus focused
  migration and reconciliation work.
- Some broker records will remain pending manual review until supported.

## Compatibility and migration

Existing `trade_episodes` remain prototype previews. They must not be promoted
to canonical lifecycle evidence or used as a migration source without raw
record linkage. A future migration must create a versioned event ledger on a
temporary database copy, preserve every raw/source identifier, and classify
existing rows as verified, review-required, or unsupported.

## Security, privacy, and financial impact

Assignments, exercises, corporate actions, and transfers can materially change
position and P&L results. Unsupported or ambiguous events must be visible as
pending and must block affected totals where necessary. The lifecycle engine is
read-only with respect to brokers.

## Validation

Tests must cover partial fills, partial exits, stock/option multi-leg groups,
rolls, assignment, exercise, expiration with and without assignment, dividends,
transfers, split adjustments, corrections, duplicate delivery, and unsupported
events. Each scenario must preserve source lineage, quantities, multipliers,
cash, and lot reconciliation.

## Rollback or supersession

This proposal changes no state. Accepted lifecycle migrations must be additive,
versioned, and reversible. A future asset-class or corporate-action ADR may
extend the event taxonomy without reinterpreting historical events silently.
