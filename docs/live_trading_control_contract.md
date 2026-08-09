# OneJournal LIV-02 → LIV-05 Control Contracts

Purpose

These contracts define the non-negotiable control envelope for future guarded
execution work (PAP-01+ and live pilot). They do not authorize live order
writes.

Status

- This file does not grant trading approval.
- It provides required evidence templates and control boundaries.

## LIV-02 — Minimal live pilot definition (read-only specification)

`docs/onejournal_product_roadmap.md` currently sets LIV-02 as a queued item.

The pilot must be explicitly declared before any write-capable execution path can
be built:

- `allowed_accounts`: allow-list of brokerage accounts
- `allowed_symbols`: allow-list of tradable symbols
- `allowed_strategies`: allow-list of approved strategy tags
- `max_quantity_by_symbol` and `max_notional_by_account`
- `max_daily_loss_notional`
- `allowed_hours`: broker/local market-hours windows
- `enabled_markets`: asset classes and option/stock restrictions
- `kill_switch_required`: true
- `force_paper_first`: true

Pilot execution policy for the first live stage:

- All settings must be explicit and environment-scoped.
- Empty or missing allow-lists must block all live writes.
- Any mismatch between operator config and control file must fail closed.
- Changes must be versioned and auditable.

Suggested pilot config evidence artifact (example structure):

```yaml
pilot:
  version: 1
  env: paper | live
  effective_from: 2026-08-10
  force_paper_first: true
  kill_switch_required: true
  allow_list:
    accounts:
      - account_id: "..."
        daily_loss_limit: 100
        max_notional: 250
    symbols:
      - SPXW
      - SPY
    strategies:
      - name: "options-income"
        max_contracts_per_order: 1
        max_orders_per_day: 4
schedule:
    enabled:
      - start_utc: "13:30"
        end_utc: "19:30"
      - start_utc: "00:00"
        end_utc: "00:00"
        disallow: true
```

Validation tooling:

- `scripts/liv/validate_pilot_config.py` validates LIV-02 pilot config documents as
  contract-compliance tests before any pilot-specific stage can be operationalized.

Validation command:

```bash
python scripts/liv/validate_pilot_config.py --config docs/live_trading_pilot_config.example.yaml
```

Failure behavior:

- Missing/invalid schema fields fail the check.
- Test/sandbox account IDs in a `live` status produce warnings.
- `--strict` upgrades warnings to hard failures and is required for staged progression.

## LIV-03 — Human approval for initial live intents

Before any live action in a new pilot stage:

- order intent must be created in a persisted state
- risk policy must evaluate as `PASS`
- an explicit human approval event must be recorded
- no implicit defaults may cause approval

Executable check:

- `scripts/liv/validate_intent_event.py --payload <path-to-intent>.json`
  validates mandatory intent fields, status enums, approval fields, and risk/approval
  consistency before an intent can move into execution handoff.

Required intent fields (minimum):

- `intent_id` (stable UUID), `source_signal_id`, `account_id`, `broker`
- `symbol`, `asset_class`, `side`, `quantity`, `order_type`, `limit_price`
- `strategy_id`, `created_at`, `status`, `risk_status`, `approval_status`,
  `approved_by`, `approved_at` (required when `approval_status=APPROVED`)
- `pilot_version`, `idempotency_key`

Required evidence:

- approve request event + approver identity
- rejection reason on denial
- expiry/replay policy (intent must not be silently retried as implicit approval)

## LIV-04 — Reconciliation for every live action

For each pilot stage, the following reconciliation chain must be operational:

1. intent_id
2. broker-order reference
3. fill batch
4. journal import row(s)
5. cash/position update snapshots

Required checks:

- orphaned intents (no broker order / no approval)
- orphaned broker orders (no approved intent)
- fill-to-intent mismatch (qty/price/sign/time drift outside tolerances)
- cash/position deltas without reconciled fills
- publication block on hard-mismatch by default

Any mismatch type must carry reasoned status (`reconciliation_pending`,
`unavailable`, `failed`) and block silent production publication.

## LIV-05 — Controlled expansion criteria

No live automation expansion should occur until all previous LIV gates are complete
and signed.

Gate for next step:

- Evidence set completed for current stage and reviewed by at least two owners.
- Post-change reconciliation error rate within the approved threshold for the
  required period.
- Rollback script and kill-switch drill completed.
- Fresh risk and compliance review against the expanded scope.

Expansion decision record:

- trigger (approved by owner + date)
- scope delta
- impact analysis
- rollback objective
- monitoring plan for 7x24h.

All expansion moves remain advisory until a separate owner approval is recorded
in a project decision record.
