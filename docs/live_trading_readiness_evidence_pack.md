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
| EVID-LIV-03-01 | LIV-03 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Approval and intent schema requirements defined; implementation pending. |
| EVID-LIV-04-01 | LIV-04 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Reconciliation chain requirements defined; checks pending implementation. |
| EVID-LIV-05-01 | LIV-05 | `docs/live_trading_control_contract.md` | PENDING | Project owner | — | Expansion gates defined; expansion decision record pending. |

## Completion rule

Queue cannot advance to a new LIV stage until all evidence rows for the current
stage are marked `OK` and cross-referenced in:

- `docs/live_trading_readiness_checklist.md`
- `docs/onejournal_product_roadmap.md`
- A formal owner signature/review artifact.

## Audit note

This evidence pack is for readiness governance only and does **not** enable live
order writes or any production execution code.
