# Spreadsheet to OneJournal Mapping

## Purpose

This document preserves the useful thinking developed through the existing TGPS
spreadsheet workflow and traces it to durable OneJournal capabilities.

The objective is not to reproduce a workbook. It is to retain the decisions,
controls, calculations, review habits, and lessons that made the spreadsheet
valuable while replacing hidden formulas, manual state, duplicated values, and
fragile file workflows with explicit contracts and evidence.

## Source-of-truth boundary

The TGPS spreadsheet and retained legacy code are historical product evidence,
not active OneJournal runtime components or automatically approved requirements.
They may reveal user intent and useful workflow concepts. Current OneJournal
contracts, accepted architecture decisions, canonical data, implementation, and
validation evidence determine how those concepts are delivered.

Do not copy a formula, field, status, tab, or workflow until its meaning,
inputs, units, failure behaviour, and downstream use are understood.

## Evolution map

| TGPS spreadsheet thinking | Value to preserve | OneJournal capability | Strategic and delivery anchors |
|---|---|---|---|
| Manual trade and broker-data capture | A complete record of what was known and entered | Immutable raw evidence, broker adapters, normalized records, import audit, and reconciliation | Vision: evidence before interpretation; roadmap FND, CON, and JRN queues |
| Rows and identifiers used to track activity | Continuity from source event to trade history | Stable record identity, source lineage, idempotent replay, corrections, and lifecycle events | ADR-0005 and ADR-0006; roadmap CON-05 and JRN-01 through JRN-06 |
| Grouping fills into a trade or strategy | Understanding the economic lifecycle rather than isolated transactions | Deterministic trade episodes, multi-leg handling, and typed lifecycle events | ADR-0005; roadmap CON-04 and JRN-03 through JRN-05 |
| Workbook formulas for P&L and returns | Repeatable financial interpretation | Versioned decimal-safe calculation services with explicit units, lot policy, inputs, and unavailable states | ADR-0003 and ADR-0004; roadmap CON-02, CON-03, and PNL queue |
| Position and portfolio summary tabs | A concise view of holdings, exposure, and financial state | Broker-reconciled positions, approved market marks, historical portfolio snapshots, and account/consolidated views | ADR-0007 and ADR-0009; roadmap PNL-02 through PNL-04 and PNL-08 |
| Performance breakdowns and time-based reports | Learning which accounts, symbols, strategies, and periods contribute to results | Canonical metrics, traceable breakdowns, period reports, and exports that reconcile to portfolio totals | Roadmap PNL-05 through PNL-07 |
| Strategy labels and planned actions | Preserve the owner's trading intent and allow later comparison with outcomes | Separate owner strategy catalog, structured pre-trade plans, tags, and links to canonical episodes | ADR-0008; roadmap UXJ-01, UXJ-03, and UXJ-04 |
| Notes, review fields, mistakes, and lessons | Turn activity into repeatable learning | Append-only journal entries and revisions, structured reviews, reusable tags, review queues, and private evidence | ADR-0008; roadmap UXJ-01 through UXJ-05 |
| Manual filters, watch lists, and exception checks | Focus attention on incomplete, unusual, risky, or unreviewed items | Search, saved views, reason-coded review queues, data-quality states, and explicit reconciliation failures | Roadmap UXJ-02, UXJ-04, and PNL-08 |
| Workbook snapshots and saved copies | Retain historical context and support comparison over time | As-of-aware canonical state, append-only history, versioned calculations, and reproducible reports | ADR-0003, ADR-0006, and ADR-0008; roadmap JRN-06 and PNL-04 through PNL-07 |
| Editable execution queues and order-management workflow | Convert reviewed intent into controlled action | A separately isolated, audited execution plane with approvals, risk gates, idempotency, reconciliation, and kill switches | ADR-0001; roadmap PAP and LIV queues; not authorized by journal implementation |

## Traceability record

When a spreadsheet concept materially affects a OneJournal feature or decision,
record:

- The spreadsheet concept and the user need it served.
- Representative evidence or examples, without committing private workbook data.
- The meaning of its fields, formulas, units, states, and exceptions.
- The OneJournal capability and authoritative contract that replace it.
- The roadmap item or architecture decision that controls delivery.
- What is designed, implemented, validated, and operationally accepted.
- Known gaps, rejected mechanics, and migration or reconciliation risks.
- The decision owner and evidence required for the next maturity step.

Use the [Capability Maturity Map](capability_maturity_map.md) to track maturity.
Do not mark a concept preserved merely because a similarly named screen, field,
or calculation exists.

## Preservation test

Before considering a spreadsheet concept successfully evolved, verify:

1. The original user decision or learning need is explicit.
2. Source evidence and identity are preserved.
3. Calculations and transformations are versioned and reproducible.
4. Manual exceptions and incomplete states remain visible.
5. The result reconciles to the appropriate canonical records.
6. The replacement is usable without relying on hidden workbook state.
7. Operational acceptance is supported separately from implementation.

## Maintenance

Update this map when a newly examined TGPS workflow reveals a distinct product
need, when a mapped concept is rejected or reinterpreted, or when architecture
changes the target capability. Do not duplicate volatile roadmap status here;
the roadmap controls delivery sequencing and the maturity map records the
evidence boundary.
