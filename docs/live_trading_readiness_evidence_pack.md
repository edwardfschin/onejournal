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
- `IN_REVIEW` — tooling/contract implemented, awaiting official queue approval.
- `OK` — evidence and owner sign-off captured.

## Evidence table

| Evidence ID | Queue item | Artifact | Status | Owner | Timestamp (UTC) | Notes |
|---|---|---|---|---|---|---|
| EVID-LIV-01-01 | LIV-01 | `docs/live_trading_readiness_evidence/legal_readiness_template.md` | OK | Project owner | 2026-08-09 | Internal owner-attested readiness declaration; production legal approval still required. |
| EVID-LIV-01-02 | LIV-01 | `docs/live_trading_readiness_evidence/security_readiness_template.md` | OK | Project owner | 2026-08-09 | Internal owner-attested security readiness; production security review still required. |
| EVID-LIV-01-03 | LIV-01 | `docs/live_trading_readiness_evidence/risk_readiness_template.md` | OK | Project owner | 2026-08-09 | Internal owner-attested operational risk controls; live thresholds still pending external approval. |
| EVID-LIV-02-01 | LIV-02 | `docs/live_trading_control_contract.md` | IN_REVIEW | Project owner | 2026-08-09 | Pilot scope policy template now contains validator-aligned fields and explicit risk/kill-switch requirements. |
| EVID-LIV-02-02 | LIV-02 | `docs/live_trading_readiness_evidence/liv_02_pilot_config_evidence.md` | IN_REVIEW | Project owner | 2026-08-09 | Pilot config template and validation proof captured for review. |
| EVID-LIV-02-03 | LIV-02 | `scripts/liv/validate_pilot_config.py` | IN_REVIEW | Project owner | 2026-08-09 | Contract validator added; approval-gated signed config is still pending. |
| EVID-LIV-03-01 | LIV-03 | `docs/live_trading_readiness_evidence/liv_03_intent_event_evidence.md` | IN_REVIEW | Project owner | 2026-08-09 | Human-approval payload schema contract formalized with validation example artifact. |
| EVID-LIV-03-02 | LIV-03 | `scripts/liv/validate_intent_event.py` | IN_REVIEW | Project owner | 2026-08-09 | Intent payload validator added for approval/risk consistency checks. |
| EVID-LIV-04-01 | LIV-04 | `docs/live_trading_readiness_evidence/liv_04_reconciliation_evidence.md` | IN_REVIEW | Project owner | 2026-08-09 | Reconciliation chain validation contract formalized with sample manifest and validator evidence. |
| EVID-LIV-04-02 | LIV-04 | `scripts/liv/validate_reconciliation_chain.py` | IN_REVIEW | Project owner | 2026-08-09 | Reconciliation chain validator added for orphan checks and aggregate consistency. |
| EVID-LIV-05-01 | LIV-05 | `docs/live_trading_readiness_evidence/liv_05_expansion_governance_evidence.md` | IN_REVIEW | Project owner | 2026-08-09 | Expansion decision template and governance checks are in place; explicit approval still pending. |
| EVID-LIV-05-02 | LIV-05 | `docs/live_trading_readiness_decision_log.md` | PENDING | Project owner | — | Stage decisions and approvals are logged; entries remain deferred pending owner approvals. |
| EVID-LIV-05-03 | LIV-05 | `scripts/liv/validate_expansion_governance.py` | IN_REVIEW | Project owner | 2026-08-09 | Governance validator added for decision log and evidence-readiness consistency. |

## Completion rule

Queue cannot advance to a new LIV stage until all evidence rows for the current
stage are marked `OK` and cross-referenced in:

- `docs/live_trading_readiness_checklist.md`
- `docs/onejournal_product_roadmap.md`
- A formal owner signature/review artifact.

## Audit note

This evidence pack is for readiness governance only and does **not** enable live
order writes or any production execution code.
