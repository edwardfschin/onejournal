# ADR-0026: Use source-declared vertical orders as presentation groups

- Status: Accepted
- Date: 2026-09-06
- Owner: OneJournal project owner
- Related: ADR-0005, ADR-0019, ADR-0025, P1-06, WEB-W06

## Context

The execution-first journal correctly preserves one lifecycle per exact
instrument when fills have no approved `episode_group_id`. That prevents false
economic grouping, but makes the two contracts of a Schwab vertical appear as
unrelated rows. The owner approved a compact, collapsible vertical header with
the exact legs indented beneath it. Mark, daily P&L, and unrealized P&L do not
belong in this historical journal summary.

Schwab order evidence explicitly identifies filled `VERTICAL` orders and their
two legs. This supports a presentation relationship, but does not authorize
merging the underlying lifecycles or calculating strategy P&L in the UI.

## Decision

OneJournal may create a versioned `schwab-vertical-presentation.v1` group only
when all of these facts agree:

- the latest reconciled assembly contains a filled Schwab order explicitly
  classified as `VERTICAL` with two legs;
- its normalized opening executions resolve to exactly two journal episodes;
- both episodes are options with the same underlying, expiry, option type, and
  currency;
- strikes differ, opening directions are opposed, and opening quantities match;
  and
- neither episode belongs to a different qualifying vertical pair.

Repeated filled opening orders for the same exact episode pair are consolidated
as scaling activity within one presentation group. The group exposes a stable
opaque identity, strategy label, status, opened time, expiry, quantity, exact
opening cash movement, fees, and two privacy-safe members. Provider order and
account identifiers are never exposed.

The UI renders a collapsible summary with the two legs indented and visually
connected. It may show reconciled opening cash paid/received and average opening
fills. It must not show Mark, daily P&L, unrealized P&L, realized P&L, max
profit, max loss, or breakeven until the relevant approved financial contract
supplies those values.

## Boundaries and consequences

- Instrument episodes, executions, lifecycle states, reviews, and P&L inputs
  remain unchanged and individually inspectable.
- Missing or ambiguous evidence remains standalone; the UI never pairs by
  ticker proximity, strike proximity, or matching timestamps alone.
- The grouping is derived read-only when the local API binds its exact database;
  no database migration or provider call is required.
- A future approved economic `episode_group_id` may supersede this
  presentation-only relationship.

## Validation and rollback

Tests must prove exact two-leg qualification, rejection of unfilled or ambiguous
orders, privacy-safe output, consolidated scaling orders, API versioning, and
responsive grouped rendering. Private evidence validation must report order,
unique-pair, and standalone counts without exposing provider identities.

Rollback removes the derived group from API/UI output and restarts the local
services. It does not restore or rewrite any journal database state.
