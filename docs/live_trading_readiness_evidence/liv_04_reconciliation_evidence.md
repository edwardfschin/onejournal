# LIV-04 Reconciliation Chain Evidence (Draft)

## Status

- Queue item: LIV-04 (Reconciliation for live actions)
- Prepared state: OK
- Author: Project owner
- Date: 2026-08-09
- Constraint: This evidence validates contract structure only; no live execution feed is connected.

## Artifacts

- Validator: `scripts/liv/validate_reconciliation_chain.py`
- Sample intents: `docs/live_trading_readiness_evidence/liv_04_sample_intents.csv`
- Sample orders: `docs/live_trading_readiness_evidence/liv_04_sample_orders.csv`
- Sample fills: `docs/live_trading_readiness_evidence/liv_04_sample_fills.csv`
- Manifest: `docs/live_trading_readiness_evidence/liv_04_reconciliation_manifest_example.json`

## Command

```bash
python scripts/liv/validate_reconciliation_chain.py --manifest docs/live_trading_readiness_evidence/liv_04_reconciliation_manifest_example.json
```

## Notes

- Intent/order/fill CSV headers follow required contract fields from
  `validate_reconciliation_chain.py`.
- Optional sections (`positions_csv`, `cash_csv`, `journal_rows_csv`) are explicitly
  absent in this draft manifest and are therefore flagged as partial-check warnings.
