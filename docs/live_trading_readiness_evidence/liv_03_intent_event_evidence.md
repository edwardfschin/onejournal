# LIV-03 Human-Approval Intents Evidence (Draft)

## Status

- Queue item: LIV-03 (Human approval for initial live intents)
- Prepared state: IN_REVIEW
- Author: Project owner
- Date: 2026-08-09
- Constraint: This evidence is schema-level only; no live intent execution path exists.

## Schema artifact

- `scripts/liv/validate_intent_event.py`
- `docs/live_trading_control_contract.md`

## Example payload

```json
{
  "intent_id": "22222222-2222-4222-b222-222222222222",
  "source_signal_id": "sig-001",
  "account_id": "ACCT-001",
  "broker": "SCHWAB",
  "symbol": "SPY",
  "asset_class": "OPTION",
  "side": "BUY",
  "quantity": 1.0,
  "order_type": "LIMIT",
  "limit_price": 500.0,
  "strategy_id": "options-income",
  "created_at": "2026-08-10T01:00:00Z",
  "risk_status": "PASS",
  "approval_status": "APPROVED",
  "approved_by": "owner-001",
  "approved_at": "2026-08-10T01:05:00Z",
  "pilot_version": "liv-pilot-001",
  "idempotency_key": "idem-001",
  "status": "NEW"
}
```

## Command

```bash
python scripts/liv/validate_intent_event.py --payload path/to/intent.json
```

## Notes

- Approval and risk consistency checks are centralized in the validator.
- This does not enable approvals in runtime; only schema and transition checks exist.
