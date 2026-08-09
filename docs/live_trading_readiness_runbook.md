# OneJournal LIV Queue Operational Runbook

## Scope

Use this runbook to execute Queue 8 readiness gates in sequence:

- LIV-01: legal/security/operational readiness review
- LIV-02: minimal live pilot definition
- LIV-03: human-approval-first intent workflow
- LIV-04: full live reconciliation chain
- LIV-05: staged expansion governance

No step may be executed if a hard blocker exists.

## Precondition

- `main` includes `JRN-05` status and the active queue ordering is in
  `docs/onejournal_product_roadmap.md`.
- `docs/live_trading_readiness_checklist.md` exists and is owned by the queue lead.
- No live broker credentials are present in the journal/write-path runtime.

## LIV-01 Execution Steps

1. Create or collect one evidence file per checklist section:
   - legal/regulatory review record
   - permission matrix
   - security model and secret-handling model
   - risk-control policy draft
2. Fill the evidence table in
   `docs/live_trading_readiness_checklist.md`.
3. Record each row as `OK` only when evidence artifact exists and has
   reviewer sign-off.
4. If any row is `WARN` or `BLOCKED`, queue remains in `LIV-01`.

## LIV-02 Execution Steps

1. Define and version pilot policy under an environment-scoped config object
   (control boundary should reject missing allow-lists).
2. Use `docs/live_trading_pilot_config.example.yaml` as the pilot template and
   persist an approved instance in your environment-specific config path.
3. Validate the environment-specific policy with:
   `python scripts/liv/validate_pilot_config.py --config <path-to-approved-pilot-config>`.
4. Ensure pilot policy is fail-closed by default and explicit about:
   accounts, symbols, strategies, size limits, and schedule.
5. Link pilot policy artifact to
   `docs/live_trading_control_contract.md` and `docs/live_trading_readiness_evidence_pack.md`.
6. Advance roadmap:
   `LIV-01` → `COMPLETE`, `LIV-02` → `NEXT`.

## LIV-03 Execution Steps

1. Define persisted intent schema and approval event schema.
2. Define approval event workflow:
   request → risk result → approval/deny → expiry/retry behavior.
3. Require explicit `approved_by` and audit correlation IDs for every send.
4. Validate there is no path where `approved=False` reaches execution.

## LIV-04 Execution Steps

1. Create end-to-end reconciliation checks for:
   intents, broker orders, fills, positions, cash, and journal import runs.
2. Define mismatch handling:
   hard mismatch → `failed`, partial uncertainty → `reconciliation_pending`.
3. Ensure publication/reporting remains fail-closed on unresolved hard mismatch.

## LIV-05 Execution Steps

1. Before any scope expansion:
   - close current evidence cycle
   - review metrics and discrepancy trend
   - confirm rollback and kill-switch drill.
2. Require at least two-owner approval for scope change.
3. Publish a decision record with timestamp + scope delta + reasons.

## Exit and handoff

- On completion of LIV-05 evidence and owner review, create a formal decision record
  in roadmap/ADR space before implementation.
- Keep execution-plane implementation on a separate branch.
- Keep paper/trading paper-trials isolated from journal reporting and Streamlit paths.
