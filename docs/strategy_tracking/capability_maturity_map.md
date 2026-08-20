# OneJournal Capability Maturity Map

## Purpose

This document tracks whether OneJournal is advancing from spreadsheet thinking
to a trusted journal, evidence-backed ledger, portfolio intelligence, and
eventually controlled automation.

It prevents code presence, a passing test, a roadmap label, or a prototype from
being reported as an operationally accepted capability.

## Evidence dimensions

Track each capability across separate dimensions:

| Dimension | Required evidence |
|---|---|
| Strategic intent | The user need and its relationship to the product vision are explicit. |
| Contract or design | Scope, semantics, boundaries, failures, security, compatibility, and acceptance criteria are approved where required. |
| Implementation | The complete in-scope producer, state, calculation, service, and consumer path exists. |
| Validation | Focused and downstream tests or reconciliations prove expected and failure behaviour against representative evidence. |
| Operational acceptance | The project owner has explicitly accepted the capability for a stated environment and scope, with remaining limitations recorded. |

These dimensions are not interchangeable. In particular:

- `COMPLETE` in the roadmap means the roadmap item's stated implementation and
  validation criteria are complete; it does not automatically mean production
  or operational acceptance.
- A prototype demonstration proves only the demonstrated path and environment.
- An accepted ADR approves a decision, not its implementation or operation.
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

Snapshot date: 2026-08-20. This summary is derived from the current product
roadmap and repository documents. It is not a new acceptance decision.

| Capability area | Evidence-backed maturity | Operational acceptance | Main gap or boundary | Roadmap anchor |
|---|---|---|---|---|
| Reproducible development foundation | M3 - Validated | No separate operational acceptance recorded; development baseline only | Continue to keep checks, dependencies, CI, and documentation truthful | FND-01 through FND-08 |
| Canonical records, journal ledger, lifecycle, identity, and reconciliation | M3 - Validated for documented repository paths | Not established for a production operating environment | Maintain real-evidence reconciliation, migration discipline, and broker-independent contracts | CON and JRN queues |
| Realized P&L | M2 - Implemented with focused contract evidence | Not accepted | Manual review of real Schwab evidence and broker-result reconciliation remain open | PNL-01 |
| Market quotes and freshness | M2 - Implemented provider-independent groundwork | Not accepted | Approved read-only provider evidence, entitlement verification, and end-to-end adapter validation remain open | PNL-02 |
| Positions, portfolio valuation, performance, and reports | M1 - Defined, with partial groundwork | Not accepted | Depends on approved quotes, broker-reconciled cumulative positions, canonical P&L, and reporting reconciliation | PNL-03 through PNL-08 |
| Structured journal and review experience | M3 - Validated in the internal prototype for completed roadmap scope | Not accepted as a production product | Runtime migration, attachment controls, financial evaluation dependencies, and production experience remain bounded or blocked | UXJ-01 through UXJ-06 |
| Production website | M0 - Identified | Not accepted | Architecture, security, design, API, authentication, implementation, and production validation remain blocked | WEB-01 through WEB-09 |
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
