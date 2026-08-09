# OneJournal LIV-01 Readiness Checklist

This document is the starting evidence pack for Queue 8 (Guarded live trading).
It is intentionally conservative: no execution decisions are encoded here.

## LIV-01 scope

- Workstream owner: OneJournal project owner + technical operator.
- Planned start: after JRN-05 gate decisions and before any paper/live write capability.
- Completion criteria: every row has evidence and status in the table below.

## 1) Legal and regulatory readiness

- [ ] Trading jurisdiction/country and broker eligibility confirmed
- [ ] User classification and permissions matrix defined (paper vs. live)
- [ ] Compliance/legal review completed and logged
- [ ] Record retention and audit expectations documented
- [ ] Terms and risk disclosures reviewed and approved for live mode

## 2) Broker and infrastructure permissions

- [ ] Separate live broker credentials and config pathway identified
- [ ] API permissions required for required operations verified in non-production first
- [ ] Broker order-write path remains separate from journal-only paths
- [ ] Fail-closed behavior confirmed when token/config/clock is stale
- [ ] Write APIs tested in paper/simulated environment before live

## 3) Security and secret handling

- [ ] Environment boundaries approved (dev/test/staging/paper/live)
- [ ] Encryption-at-rest and transport controls for secrets confirmed
- [ ] Secret rotation and emergency rotation workflow documented
- [ ] Access logging and anomaly alerting enabled for secret misuse patterns
- [ ] No runtime credentials committed in scripts, DB rows, logs, payloads, or tests

## 4) Financial and operational risk controls

- [ ] Kill switch and disable flag exists and tested
- [ ] Per-account and per-symbol limits documented
- [ ] Max notional/order size and max daily loss limits documented
- [ ] Duplicate prevention rules for intents/orders are defined
- [ ] Manual override/escalation process for unexpected fills/orders defined
- [ ] Reconciliation cadence for intents/orders/fills/positions/cash defined

## 5) Execution-plane architecture prerequisites (non-negotiable)

- [ ] Execution plane isolated from journal/presentation code paths
- [ ] Order intent schema versioned and validated before send
- [ ] Idempotency keys required for retry-safe order operations
- [ ] All live writes go through risk gates and approval path
- [ ] Evidence artifacts include intent ID, intent version, source actor, approvals

## 6) Operational readiness

- [ ] Monitoring: readiness, failures, retry rates, stale-state indicators
- [ ] Disaster recovery for order state and credential outages
- [ ] Runbook for run-stop conditions and on-call response
- [ ] Pre-live checklist review by two owners with approval signatures
- [ ] Signed completion for each evidence item in this checklist

## Evidence log

Track proof in rows:

- Date
- Item/ID
- Evidence artifact (file path or PR/record)
- Status (`OK`, `WARN`, `BLOCKED`)
- Owner
- Notes

### Checklist evidence table

| Date (UTC) | LIV item | Evidence artifact | Status | Owner | Notes |
|---|---|---|---|---|---|
| 2026-08-09 | LIV-01-1 (Legal) | `docs/live_trading_readiness_evidence/legal_readiness_template.md` | BLOCKED | Project owner | Legal/security evidence template prepared; review/sign-off still pending. |
| 2026-08-09 | LIV-01-2 (Security) | `docs/live_trading_readiness_evidence/security_readiness_template.md` | BLOCKED | Project owner | Security evidence template prepared; review/sign-off still pending. |
| 2026-08-09 | LIV-01-3 (Risk) | `docs/live_trading_readiness_evidence/risk_readiness_template.md` | BLOCKED | Project owner | Risk evidence template prepared; review/sign-off still pending. |
| 2026-08-09 | LIV-02-1 (Pilot scope config) | `docs/live_trading_control_contract.md` | BLOCKED | Project owner | Contract added; pilot settings not approved yet. |
| 2026-08-09 | LIV-03-1 (Human approval) | `docs/live_trading_control_contract.md` | BLOCKED | Project owner | Approval workflow contract created; no live intent path yet. |
| 2026-08-09 | LIV-04-1 (Reconciliation) | `docs/live_trading_control_contract.md` | BLOCKED | Project owner | Reconciliation chain contract created; implementation pending. |
| 2026-08-09 | LIV-05-1 (Expansion controls) | `docs/live_trading_control_contract.md` | BLOCKED | Project owner | Expansion gate contract created; no expansion in effect. |

## Linkages

- Queue 8 execution control details for LIV-02..LIV-05 are documented in
  `docs/live_trading_control_contract.md`.
- Execution sequencing for LIV-01..LIV-05 is documented in
  `docs/live_trading_readiness_runbook.md`.
- Evidence registry for completed artifacts is tracked in
  `docs/live_trading_readiness_evidence_pack.md`.
- Stage-completion decisions are recorded in
  `docs/live_trading_readiness_decision_log.md`.
