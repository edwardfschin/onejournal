# OneJournal Capability Maturity Map

## Purpose

This document tracks whether OneJournal is advancing from spreadsheet thinking
to a trusted journal, evidence-backed ledger, portfolio intelligence, and
eventually controlled automation.

It prevents code presence, a passing test, a roadmap label, or a prototype from
being reported as an operationally accepted capability.

## Capability dimensions

Track each capability across six independent dimensions. Strategic intent and
acceptance criteria remain required supporting context, but they do not replace
evidence in any dimension:

| Dimension | Required evidence |
|---|---|
| Policy | The required business and architecture decisions, scope, semantics, boundaries, failure rules, security, and compatibility are explicitly approved. |
| Implementation | The complete in-scope producer, state, calculation, service, and consumer path exists. |
| Validation | Focused and downstream tests or reconciliations prove expected and failure behaviour against representative evidence. |
| Migration/runtime | Required migrations are applied and the capability is available in the stated runtime environment. |
| Operational acceptance | The project owner has explicitly accepted the capability for a stated operating environment and scope, with remaining limitations recorded. |
| Financial acceptance | The project owner has explicitly accepted the capability as trustworthy for stated financial decisions, based on approved policy and reconciled financial evidence. |

These dimensions are not interchangeable. In particular:

- `COMPLETE` in the roadmap means the roadmap item's stated implementation and
  validation criteria are complete; it does not automatically mean migration,
  runtime availability, production readiness, operational acceptance, or
  financial acceptance.
- A prototype demonstration proves only the demonstrated path and environment.
- An accepted ADR establishes policy, not implementation, migration/runtime,
  validation, operational acceptance, or financial acceptance.
- Readiness documents and controls do not enable broker access, deployment, or
  live execution.

## Maturity levels

Use the lowest level supported by evidence:

| Level | Meaning |
|---|---|
| M0 - Identified | The user need or spreadsheet concept is recorded. |
| M1 - Defined | The intended capability and acceptance criteria are documented; material policy is approved where required. |
| M2 - Implemented | The in-scope code and data path exist, but validation or real evidence is incomplete. |
| M3 - Validated | The implementation passes its defined checks with representative evidence in a stated environment. |
| M4 - Operationally accepted | The project owner explicitly accepts the validated capability for a stated operating scope and environment. |
| M5 - Trusted and established | Sustained operating evidence, reconciliation, recovery, and user adoption show that the capability reliably serves its strategic purpose. |

A capability cannot advance because of elapsed time or confidence alone. Record
the evidence and acceptance decision that support every change.

## Current strategic snapshot

Snapshot date: 2026-09-07. This summary is derived from the current product
roadmap and repository documents. It is not a new acceptance decision.

| Capability area | Evidence-backed maturity | Operational acceptance | Main gap or boundary | Roadmap anchor |
|---|---|---|---|---|
| Reproducible development foundation | M3 - Validated | No separate operational acceptance recorded; development baseline only | Continue to keep checks, dependencies, CI, and documentation truthful | FND-01 through FND-08 |
| Canonical records, journal ledger, lifecycle, bounded fill identity/replay, and reconciliation | M3 - Validated for documented repository paths | Not established for a production operating environment | ADR-0006 accepts only normalized-fill identity/replay and P&L input fingerprints; maintain real-evidence reconciliation and migration discipline | CON-01 through CON-06 and JRN-01 through JRN-07 |
| Schwab Phase 1 evidence assembly and import | M4 - Operationally accepted for one bounded isolated owner-controlled account | Accepted 2026-09-06 for exact private assembly, migration-0016 persistence, replay, and read-back | Acceptance preserves 58/48/10 position/quote coverage, 423/3/7 fill reconciliation, 54 cash-currency review rows, and eight order exclusions. It does not establish an actual journal migration, production route, continuous acquisition, credential ownership, complete history, or portfolio financial correctness | P1-05 and ADR-0024 |
| Complete evidence provenance and governed correction/recalculation lineage | M0 - Identified, with partial prototype mechanisms | Not accepted | Import-run batch audit and replace-import revision rows do not establish immutable raw hashes, normalized versions, supersession, correction approval, complete invalidation, or raw-to-output lineage | Proposed ADR-0010, CON-07, and JRN-08 |
| Realized P&L | M3 - Validated for five explicitly accepted bounded real-broker lifecycle scopes | Not operationally accepted; bounded financial acceptance recorded 2026-08-27 | Acceptance covers ONJ-TRUST-01B, 02, 03, 04, and 06 only. Real exercise, roll replacement-contract closure, unresolved review-required or unapproved description-only events, complete account history, portfolio-wide correctness, unrealized P&L/valuation, and complete ADR-0010 provenance remain excluded | PNL-01 |
| Market quotes and freshness | M4 - Operationally accepted for the bounded owner-operated local Schwab bridge scope | Accepted 2026-08-31 for manual credential-free bridge intake, OneJournal-owned conversion/session/freshness, private materialization, and isolated DuckDB persistence/read-back | No continuous acquisition, public/hosted service, production journal migration, OneJournal credential ownership, or IBKR/Moomoo adapter is accepted. PNL-03 separately accepts those exact marks only inside its bounded private broker-current result; T15 cutover remains later target-architecture work | PNL-02 |
| Current positions and broker-current valuation | M4 - Operationally accepted for the bounded private single-owner local Schwab scope | Accepted 2026-09-07 for the exact persisted 58-position result and demonstrated WEB-W07 loopback API/application slice | PNL-03 provides 58/58/58 cost-basis, market-value, and unrealized-P&L availability with per-position Schwab reconciliation. Migrations through 0023, exact persistence, one value-free read audit, responsive browser checks, and fail-closed unavailable behavior are accepted only for this local scope. Continuous acquisition, credential ownership, authenticated hosting, deployment, broader or realized P&L, and complete transferred-lot realized P&L remain excluded | P1-07, PNL-03, and WEB-W07 |
| Historical portfolio state, performance, and reports | M1 - Defined, with partial groundwork | Not accepted | Canonical historical snapshots, complete realized/unrealized integration, bounded Phase 1 breakdown/history/export, broader analytics, and production presentation remain open | PNL-04 through PNL-08 |
| Structured journal and review experience | M4 - Operationally accepted for the current private local-owner loopback scope | Accepted 2026-09-07 for WEB-W06's current local release scope | The accepted slice preserves append-only reviews/entries, exact execution/lifecycle inspection, privacy, and fail-closed financial boundaries. Further visual refinement is backlog; attachments, hosted authentication, production deployment, and broader journal workflows remain bounded or blocked | P1-06, WEB-W06, and UXJ-01 through UXJ-06 |
| Production website | M3 - Validated, with two operationally accepted local-owner slices | Not accepted as a complete production product | ADR-0017 defines the React/TypeScript/Vite/FastAPI foundation. WEB-W06 and WEB-W07 are owner-accepted for their bounded private local loopback scopes. Authentication, hosted runtime, deployment, later report/data-health/settings and broader P&L slices, and complete production validation remain outstanding | P1-01 through P1-12, WEB-01 through WEB-09, and WEB-W01 through WEB-W13 |
| Production operations and resilience | M0 - Identified | Not accepted | Environment boundaries, deployment, recovery, observability, security, privacy, and incident policies remain blocked | OPS-01 through OPS-07 |
| Paper-trading execution plane | M0 - Identified for later work | Not accepted or enabled | Requires a separately approved execution architecture and all paper-trading gates | PAP-01 through PAP-07 |
| Guarded live trading | M1 - Readiness controls documented | Not accepted or enabled | External review, paper evidence, explicit authorization, deployment, and bounded operating approval remain separate requirements | LIV-01 through LIV-05 and PAP gates |

## Update rules

Update this map when a capability crosses a maturity boundary or when evidence
shows that a previous claim must be downgraded.

For each change:

1. Link the capability to the product vision and spreadsheet evolution map.
2. Identify the authoritative ADR, contract, roadmap item, and implementation.
3. Record validation evidence, environment, scope, date, and limitations.
4. Record operational acceptance separately, including who approved what scope.
5. Downgrade the maturity level if evidence, compatibility, reconciliation, or
   operating assumptions no longer hold.

Do not use this document to bypass roadmap dependencies or approval boundaries.
The roadmap controls delivery order, accepted ADRs and contracts control durable
policy, implementation controls actual behaviour, and explicit evidence controls
maturity claims.

## Strategic review cadence

Review the three strategic anchors at material roadmap or architecture decision
points and before declaring a major capability complete. The review should ask:

- Are we still building the product described by the vision?
- Is useful TGPS spreadsheet thinking preserved without carrying forward fragile
  mechanics?
- Does the claimed maturity match repository and operational evidence?
- Are the next roadmap decisions closing the most important strategic gap?
- Have implementation and operational acceptance remained clearly separated?
