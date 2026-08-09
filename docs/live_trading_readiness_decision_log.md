# OneJournal LIV Decision Log (Queue 8)

Use this log to record stage-completion approvals before advancing LIV items.

## Record format

Each entry should include:

- Date (UTC)
- Queue item (LIV-01 / LIV-02 / LIV-03 / LIV-04 / LIV-05)
- Decision status (`COMPLETED`, `BLOCKED`, `CHANGES_REQUIRED`, `DEFERRED`)
- Artifact references (files, PRs, screenshots, signatures)
- Reviewer and approver identity
- Rationale / scope constraints
- Next action and explicit owner

## Entries

| Date (UTC) | Queue item | Decision status | Artifact(s) | Approver | Approver role | Rationale / constraints | Next action |
|---|---|---|---|---|---|---|---|
| 2026-08-09 | LIV-01 | DEFERRED | `docs/live_trading_readiness_checklist.md`<br>`docs/live_trading_readiness_evidence_pack.md`<br>`docs/live_trading_control_contract.md`<br>`docs/live_trading_readiness_runbook.md` | Project owner | Owner | Readiness artifacts created; review evidence pending. | Collect legal/security/risk evidence rows and obtain approvals before moving LIV-01 to COMPLETE. |
| 2026-08-09 | LIV-02 | DEFERRED | `docs/live_trading_control_contract.md` | — | — | Pilot policy contract is documented but not operationalized. | Produce environment-scoped pilot config and control-file validation evidence. |
| 2026-08-09 | LIV-03 | DEFERRED | `docs/live_trading_control_contract.md` | — | — | Approval/intents schema model exists only as contract text. | Define/publish intent schema versioning and approval/audit event format. |
| 2026-08-09 | LIV-04 | DEFERRED | `docs/live_trading_control_contract.md` | — | — | Reconciliation chain currently design-only. | Implement and validate live intent → order → fill → journal reconciliation checks. |
| 2026-08-09 | LIV-05 | DEFERRED | `docs/live_trading_control_contract.md` | — | — | Expansion gates are specified but no staged expansion executed. | Run expansion drill plan and governance checklist. |
