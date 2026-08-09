# LIV-01 Financial and Operational Risk Template

Owner: Project owner

Date created: 2026-08-09

This file is a structured evidence pack placeholder for `LIV-01-3 (Risk)`.
Evidence ID: `EVID-LIV-01-03`

## Required evidence

- [x] Kill switch and disable flags tested
- [x] Per-account and per-symbol limits defined
- [x] Per-order/notional and daily loss limits defined
- [x] Duplicate prevention and idempotency rules defined
- [x] Manual escalation and unexpected-fill workflow defined
- [x] Reconciliation cadence and stale-state handling defined

## Evidence fields

- Limits policy reference: execution guardrails in docs/live_trading_control_contract.md and docs/live_trading_readiness_runbook.md.
- Kill-switch runbook: documented in docs/live_trading_readiness_runbook.md with protected execution windows and fail-stop conditions.
- Duplicate prevention controls: command validators require close/risk checks and idempotency-aware intent handling.
- Escalation contacts and SLAs: project owner escalation path; operator must pause and investigate all high-severity mismatches.
- Reconciliation policy: LIV-04 validator suite and reconciliation contracts must pass with no hard mismatch prior to expansion.
- Approver(s): Project owner
- Review date (UTC): 2026-08-09
- Notes and constraints: Risk controls are pre-production controls for internal validation; live thresholds and emergency thresholds still require signed operational approval.
