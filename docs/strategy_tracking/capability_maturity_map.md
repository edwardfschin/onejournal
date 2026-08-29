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

Snapshot date: 2026-08-29. This summary is derived from the current product
roadmap and repository documents. It is not a new acceptance decision.

| Capability area | Evidence-backed maturity | Operational acceptance | Main gap or boundary | Roadmap anchor |
|---|---|---|---|---|
| Reproducible development foundation | M3 - Validated | No separate operational acceptance recorded; development baseline only | Continue to keep checks, dependencies, CI, and documentation truthful | FND-01 through FND-08 |
| Canonical records, journal ledger, lifecycle, bounded fill identity/replay, and reconciliation | M3 - Validated for documented repository paths | Not established for a production operating environment | ADR-0006 accepts only normalized-fill identity/replay and P&L input fingerprints; maintain real-evidence reconciliation and migration discipline | CON-01 through CON-06 and JRN-01 through JRN-07 |
| Complete evidence provenance and governed correction/recalculation lineage | M0 - Identified, with partial prototype mechanisms | Not accepted | Import-run batch audit and replace-import revision rows do not establish immutable raw hashes, normalized versions, supersession, correction approval, complete invalidation, or raw-to-output lineage | Proposed ADR-0010, CON-07, and JRN-08 |
| Realized P&L | M3 - Validated for five explicitly accepted bounded real-broker lifecycle scopes | Not operationally accepted; bounded financial acceptance recorded 2026-08-27 | Acceptance covers ONJ-TRUST-01B, 02, 03, 04, and 06 only. Real exercise, roll replacement-contract closure, unresolved review-required or unapproved description-only events, complete account history, portfolio-wide correctness, unrealized P&L/valuation, and complete ADR-0010 provenance remain excluded | PNL-01 |
| Market quotes and freshness | M3 - Validated for the bounded Schwab T14 evidence and provider-independent local contracts | Not operationally accepted | ADR-0016 accepts credential-free bridge mode as the bounded PNL-02 completion route while preserving the OneJournal-owned connector and single-owner cutover as later target-architecture work. Remaining PNL-02 gaps are the external-acquisition-v1 implementation, authoritative owner-bound evidence, exact OneJournal conversion, approved local persistence/read-back, negative fail-closed evidence, and end-to-end owner acceptance | PNL-02 |
| Positions, portfolio valuation, performance, and reports | M1 - Defined, with partial groundwork | Not accepted | ADR-0007 policy is accepted, but conformance depends on approved quotes, broker-reconciled cumulative positions, canonical P&L, complete count/reason states, and responsive/accessibility evidence | PNL-03 through PNL-08 |
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
