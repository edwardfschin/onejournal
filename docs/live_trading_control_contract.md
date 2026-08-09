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

- `pilot.allow_list.accounts`: allow-list of brokerage accounts
- `pilot.allow_list.symbols`: allow-list of tradable symbols
- `pilot.allow_list.strategies`: allow-list of approved strategy tags
- `pilot.risk_limits.max_quantity_per_order`, `...max_notional_per_order`, `...max_notional_daily`
- `pilot.allow_list.accounts[].max_daily_loss_limit`
- `pilot.schedule.enabled_windows_utc`: broker-market-time windows in UTC
- `pilot.risk_limits.allowed_sessions` and `pilot.schedule.timezone`
- `kill_switch_required`: true
- `force_paper_first`: true in paper-first phases

Pilot execution policy for the first live stage:

- All settings must be explicit and environment-scoped.
- Empty or missing allow-lists must block all live writes.
- Any mismatch between operator config and control file must fail closed.
- Changes must be versioned and auditable.

Suggested pilot config evidence artifact (matching schema fields):

```yaml
pilot:
  version: 1
  policy_id: "liv-pilot-001"
  status: paper | live
  environment: paper | live
  effective_from_utc: "2026-08-10T00:00:00Z"
  force_paper_first: true
  kill_switch_required: true
  kill_switch_env_var: "ONEJOURNAL_LIV_KILL_SWITCH"
  allow_list:
    accounts:
      - id: "ACCOUNT_ID_1"
        currency: "USD"
        max_notional: 250
        max_daily_loss_limit: 100
        max_orders_per_day: 4
    symbols:
      - symbol: "SPY"
        max_qty: 1
      - symbol: "SPXW"
        max_qty: 1
    strategies:
      - "options-income"
      - "defined-risk-spreads"
  risk_limits:
    max_notional_per_order: 500
    max_notional_daily: 1500
    max_quantity_per_order: 2
    max_position_delta_notional: 2500
    min_market_hours_only: true
    allowed_sessions:
      - "RTH"
schedule:
  timezone: "America/New_York"
  enabled_windows_utc:
    - start_time: "13:30"
      end_time: "20:00"
    - start_time: "21:00"
      end_time: "23:59"
      allow: false
  controls:
    duplicate_prevention:
      require_idempotency_key: true
      duplicate_tolerance_seconds: 120
    approvals:
      requires_two_step_approval: false
      default_ttl_minutes: 120
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

Executable check:

- `scripts/liv/validate_reconciliation_chain.py --manifest <reconciliation-manifest>.json`
  validates orphaned intents/orders/fills, fill-to-intent consistency, and
  completeness checks before advancing LIV-04.

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

Executable check:

- `scripts/liv/validate_expansion_governance.py \
  --decision-log docs/live_trading_readiness_decision_log.md \
  --evidence-pack docs/live_trading_readiness_evidence_pack.md`
  validates decision-log structure and evidence completeness before expansion is
  proposed.
