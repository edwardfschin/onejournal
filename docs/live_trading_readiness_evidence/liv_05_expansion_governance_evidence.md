# LIV-05 Controlled Expansion Evidence (Draft)

## Status

- Queue item: LIV-05 (Controlled expansion criteria)
- Prepared state: OK
- Author: Project owner
- Date: 2026-08-09
- Constraint: External approvals are still required before production expansion; this is owner sign-off only.

## Artifacts

- Governance validator: `scripts/liv/validate_expansion_governance.py`
- Governance decision ledger: `docs/live_trading_readiness_decision_log.md`
- Control contract: `docs/live_trading_control_contract.md`

## Validation command

```bash
python scripts/liv/validate_expansion_governance.py \
  --decision-log docs/live_trading_readiness_decision_log.md \
  --evidence-pack docs/live_trading_readiness_evidence_pack.md
```

## Decision template (owner action required)

- Trigger + scope delta
- Impact/risk assessment
- Rollback objective
- Monitoring plan (at least 7x24h)
- At least two-owner approval for scope change

## Notes

- Current ledger remains `DEFERRED` for LIV-05, so this row is intentionally
  `IN_REVIEW` and not marked `OK`.
