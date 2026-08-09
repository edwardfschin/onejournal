# LIV-02 Pilot Configuration Evidence (Draft)

## Status

- Queue item: LIV-02 (Minimal live pilot definition)
- Prepared state: IN_REVIEW
- Author: Project owner
- Date: 2026-08-09
- Constraint: Proof-only; no production write-path is enabled in this branch.

## Artifacts

- Control contract: `docs/live_trading_control_contract.md`
- Pilot template: `docs/live_trading_pilot_config.example.yaml`
- Validator: `scripts/liv/validate_pilot_config.py`

## Command

```bash
python scripts/liv/validate_pilot_config.py --config docs/live_trading_pilot_config.example.yaml
```

## Notes

- Schema is environment-scoped (`paper`/`live`) with strict type checks for
  accounts, symbols, strategies, risk limits, schedule windows, and approval controls.
- Validation currently includes a warning (`--warn`) path for live/test-account edge
  cases; no live broker write is connected in this repository.
