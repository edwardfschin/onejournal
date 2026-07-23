# ADR-0007: Define data freshness, reconciliation, and fail-closed presentation

- Status: Proposed
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-06, PNL-02 through PNL-08, WEB-01 through WEB-09
- Related contracts: ADR-0003 through ADR-0006,
  `docs/import_run_audit_contract.md`,
  `docs/schwab_orders_transactions_reconciliation.md`
- Supersedes: None
- Superseded by: None

## Context

The current prototype records import runs and reconciles same-date Schwab
orders-normalized fills against transactions-normalized fills. It has no
position/mark/market-data pipeline, freshness SLA, stale-price state, or
portfolio-level reconciliation. The dashboard payload contains generated time
and simple episode previews but does not publish data quality or completeness
for financial totals.

Displaying a stale mark, incomplete import, or unreconciled broker state as a
normal portfolio/P&L number would be misleading.

## Decision

Subject to project-owner approval, every published financial value and report
will carry machine-readable freshness and completeness metadata.

- Each source dataset records provider, retrieval/import run, source evidence,
  as-of instant, received time, validation time, status, counts, warnings, and
  failure reason where applicable.
- A portfolio/P&L result has one of: `valid`, `stale`, `incomplete`,
  `reconciliation_pending`, `unavailable`, or `failed`. A status applies to
  the exact metric and scope, not only the whole page.
- `valid` requires all required data to be present, validated, within an
  approved freshness threshold, and reconciled to the level required by the
  metric. Freshness thresholds are not invented here; they are approved with
  the future market-data provider and product service-level decision.
- `stale` means evidence is usable but beyond the approved threshold. Its age,
  source time, and last successful update remain visible. Stale data cannot be
  labelled current, live, or valid.
- `incomplete` means a required input is missing, unsupported, or partially
  imported. `reconciliation_pending` means evidence exists but has not passed
  the required comparison. `unavailable` means the metric cannot be calculated
  safely. `failed` means a required operation failed and identifies its reason
  without exposing private data.
- A financial aggregate inherits the most restrictive applicable input state.
  It may show a separately labelled partial/native-currency subtotal only when
  the omitted scope and reason are explicit; it must not present that subtotal
  as a consolidated total.
- The UI deliberately designs loading, empty, stale, partial, pending, failed,
  and no-activity states. Zero is displayed only when the system has valid
  evidence that the mathematical value is zero.
- Reconciliation compares the appropriate authority for the metric: fills to
  transaction/accounting evidence, positions/lots to broker position snapshots,
  cash to broker cash evidence, and calculated P&L to explainable broker
  evidence. A discrepancy opens an auditable exception rather than being
  overwritten.

## Boundaries

This decision does not select a market-data provider, quote type, exchange
calendar, exact freshness duration, alert channel, availability target, or
incident-response policy. It does not make the Streamlit prototype a production
website or authorize background broker polling.

## Alternatives considered

### Show the last successful value without status

This is visually simple but can represent stale or incomplete evidence as
current financial information. Rejected.

### Replace missing values with zero

This hides data loss and makes calculations appear complete. Rejected.

### Block the entire UI on any data issue

This hides useful independent information. Rejected: unaffected panels may be
shown with their own status, while affected totals fail closed.

## Consequences

### Positive

- Users can distinguish a valid result from a useful-but-stale snapshot.
- Data failures become actionable operational evidence rather than silent UI
  defects.
- Future web/API contracts have consistent state vocabulary.

### Negative and trade-offs

- Every producer, payload, API, and UI panel needs status metadata and tests.
- A provider selection and service-level decision are required before any metric
  can claim `valid` freshness.

## Compatibility and migration

Existing payloads and dashboard summaries lack these fields and must be treated
as prototype/limited, not financially authoritative. A versioned payload
contract must add per-metric status without causing clients to interpret absent
status as valid. Current import/reconciliation output becomes an input to the
new quality model; it is not by itself proof of portfolio completeness.

## Security, privacy, and financial impact

Status and failure reasons must be actionable without exposing account numbers,
tokens, holdings, raw broker payloads, or private paths. A missing or stale
input can materially misstate portfolio and P&L values, so affected values must
fail closed.

## Validation

Implementation must test fresh, stale, missing, partial, failed, zero-activity,
unreconciled, reconciliation-mismatch, native-currency-only, and recovery
states. It must prove aggregate state propagation, visible as-of/source times,
no false zero, no false `valid`, payload/API compatibility, and desktop/tablet/
mobile accessibility of each state.

## Rollback or supersession

This proposal changes no runtime output. An accepted implementation must be
versioned and deployed behind validated producers/consumers. A later market-data
or service-level ADR supplies thresholds and may supersede the relevant parts
without weakening existing fail-closed behavior.
