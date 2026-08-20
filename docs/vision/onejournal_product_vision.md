# OneJournal Product Vision

## Purpose

OneJournal exists to become the trusted financial memory and intelligence
system for a serious individual trader.

It turns fragmented broker activity, manual records, trade decisions, and review
notes into an explainable financial history. It should help the owner understand
what happened, why it happened, what evidence supports it, how the financial
result was calculated, and what should change next.

## North star

Every material record and displayed financial result should be explainable and
reproducible.

A user should be able to trace:

```text
product view or financial result
-> calculation or interpretation
-> canonical journal state
-> normalized broker-independent records
-> original evidence
-> source event and as-of time
```

If required evidence is missing, stale, unsupported, or unreconciled,
OneJournal should show that limitation rather than invent a complete-looking
answer.

## Product promise

OneJournal will provide:

- A durable, broker-independent record of trading activity and decisions.
- Traceable portfolio, P&L, performance, and risk information.
- Structured review that connects plans, actions, outcomes, mistakes, and
  lessons without rewriting financial evidence.
- Clear freshness, completeness, reconciliation, and calculation context.
- A polished product experience built on trustworthy financial and journal
  foundations.
- A foundation for separately controlled automation only after its safety and
  operating gates are explicitly accepted.

## Strategic principles

### Trust before breadth

Correctness, lineage, reconciliation, privacy, and failure clarity come before
more brokers, asset classes, analytics, or presentation features.

### Evidence before interpretation

Preserve original source evidence. Normalize it without losing identity or
lineage. Derive journal and financial views from canonical records instead of
manually repairing outputs.

### Explainability before automation

Calculations, classifications, and recommendations must expose their inputs,
rules, versions, and limitations. Automation must not hide uncertainty or
bypass review and safety controls.

### Broker independence

Broker-specific details stop at adapter boundaries. Journal, portfolio, P&L,
review, and presentation capabilities use stable OneJournal contracts.

### Financial truth and authored reflection are distinct

Broker evidence and calculated financial state remain authoritative within
their approved contracts. Plans, notes, strategies, mistakes, and lessons add
meaning without mutating that evidence.

### Product progress is not operational acceptance

A design, implementation, passing test, or prototype demonstration is not proof
that a capability is ready for operational or production use. Acceptance must
be explicit, scoped, and supported by evidence.

### Controlled evolution

OneJournal should progress through increasingly capable stages without skipping
their trust gates:

```text
spreadsheet thinking
-> structured journal
-> evidence-backed ledger
-> portfolio and performance intelligence
-> controlled automation
```

Each stage should preserve the useful intent and learning of the previous stage
while replacing fragile mechanics with explicit contracts and validation.

## Product boundaries

OneJournal is not:

- A broker or a replacement for broker statements.
- A transcription of spreadsheet tabs, formulas, and manual workarounds.
- A black-box trading signal or financial-advice system.
- Authority to place, change, or cancel orders through journal or presentation
  paths.
- A claim that implementation alone establishes production readiness.

The approved product scope, broker sequence, asset coverage, and execution
boundaries remain controlled by the roadmap and accepted architecture decisions.

## Decision test

Architecture, roadmap, and product decisions should be tested against these
questions:

1. Does this strengthen or weaken trust in the financial memory?
2. Can the result be traced to evidence, rules, versions, and an as-of time?
3. Does it preserve broker independence and separation of concerns?
4. Does it make incomplete or unsafe states explicit?
5. Does it preserve the useful intent of the existing workflow without carrying
   forward fragile spreadsheet mechanics?
6. Is the claimed maturity supported by implementation, validation, and
   acceptance evidence appropriate to the stated scope?

If a proposed decision conflicts with this vision, record and approve the
strategic change before treating it as durable project policy.

## Related strategic anchors

- [Spreadsheet to OneJournal Mapping](../strategy_tracking/spreadsheet_to_onejournal_mapping.md)
- [Capability Maturity Map](../strategy_tracking/capability_maturity_map.md)
- [OneJournal Product Roadmap](../onejournal_product_roadmap.md)
