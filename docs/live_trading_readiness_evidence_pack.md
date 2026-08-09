# OneJournal LIV Evidence Pack (Queue 8, LIV-01 to LIV-05)

This pack records concrete evidence artifacts for the readiness and execution-control
queue so the project can move from documentation to review.

## Evidence ID naming

- `EVID-LIV-01-xxx`  -> LIV-01 readiness evidence
- `EVID-LIV-02-xxx`  -> LIV-02 pilot and policy scope evidence
- `EVID-LIV-03-xxx`  -> LIV-03 approval/intents evidence
- `EVID-LIV-04-xxx`  -> LIV-04 reconciliation evidence
- `EVID-LIV-05-xxx`  -> LIV-05 expansion-control evidence

## Status map

- `PENDING` — required evidence has not yet been collected.
- `BLOCKED` — evidence dependency missing or disapproved.
- `OK` — evidence and owner sign-off captured.

## Evidence table

| Evidence ID | Queue item | Artifact | Status | Owner | Timestamp (UTC) | Notes |
|---|---|---|---|---|---|---|
| EVID-LIV-01-01 | LIV-01 | `docs/live_trading_readiness_checklist.md` | PENDING | Project owner | — | Legal/compliance sign-off evidence still to be attached. |
| EVID-LIV-01-02 | LIV-01 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Secret/session control model and separation controls pending draft/approval. |
| EVID-LIV-01-03 | LIV-01 | `docs/live_trading_readiness_runbook.md` | PENDING | Project owner | — | Runbook sequencing defined; first completed run entry pending. |
| EVID-LIV-02-01 | LIV-02 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Pilot scope policy template present; operational config file not yet produced. |
| EVID-LIV-02-02 | LIV-02 | `docs/live_trading_pilot_config.example.yaml` | PENDING | Project owner | — | Template pilot control file created for versioned governance. |
| EVID-LIV-02-03 | LIV-02 | `scripts/liv/validate_pilot_config.py` | IN_REVIEW | Project owner | — | Contract validator added; add proof of first production-approved signed config file. |
| EVID-LIV-03-01 | LIV-03 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Approval and intent schema requirements defined; implementation pending. |
| EVID-LIV-03-02 | LIV-03 | `scripts/liv/validate_intent_event.py` | IN_REVIEW | Project owner | — | Intent payload validator added for approval/risk consistency checks. |
| EVID-LIV-04-01 | LIV-04 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Reconciliation chain requirements defined; checks pending implementation. |
| EVID-LIV-04-02 | LIV-04 | `scripts/liv/validate_reconciliation_chain.py` | IN_REVIEW | Project owner | — | Reconciliation chain validator added for orphan checks and aggregate consistency. |
| EVID-LIV-05-01 | LIV-05 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Expansion gates defined; expansion decision record pending. |
| EVID-LIV-05-02 | LIV-05 | `docs/live_trading_readiness_decision_log.md` | PENDING | Project owner | — | Stage decisions and approvals are logged; initial entries show deferred state. |
| EVID-LIV-05-03 | LIV-05 | `scripts/liv/validate_expansion_governance.py` | IN_REVIEW | Project owner | — | Governance validator added for decision log and evidence-readiness consistency. |

## Completion rule

Queue cannot advance to a new LIV stage until all evidence rows for the current
stage are marked `OK` and cross-referenced in:

- `docs/live_trading_readiness_checklist.md`
- `docs/onejournal_product_roadmap.md`
- A formal owner signature/review artifact.

## Audit note

This evidence pack is for readiness governance only and does **not** enable live
order writes or any production execution code.
