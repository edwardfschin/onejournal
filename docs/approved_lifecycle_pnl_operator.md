# Approved Lifecycle P&L Operator

## Purpose and boundary

`scripts/journal/rebuild_pnl_allocations.py` calculates durable FIFO P&L from
normalized fills plus manually approved assignment, exercise, or expiration
instructions. It implements accepted ADR-0004 economic/book accounting; it is
not a tax calculator.

The command never calls a broker or order API, never edits raw/normalized
evidence, and is dry-run by default. `--apply` writes only reviewed instruction
records and a new append-only calculation run. Applying migrations or using a
live journal database remains a separate approval boundary.

## Preconditions

- The database has migrations 0008 through 0010 on a temporary copy.
- Every participating fill and lifecycle header has canonical UTC evidence.
- The event header and evidence legs are already normalized and retained.
- The owner/operator has confirmed the event type, predecessor contract and
  direction, exact FIFO source fills, contracts, multiplier/deliverable,
  event costs, and successor economics where applicable.
- `description_hint`, `review_required`, or incomplete evidence is not approved.

## Reviewed instruction CSV

Required columns are:

```text
event_uid,event_type,source_broker,source_account_id,currency,effective_at,option_instrument_key,predecessor_direction,contracts,predecessor_open_fill_uids_json,event_commission,event_fees,evidence_status,source_event_leg_uids_json,successor_action,successor_position_effect,successor_symbol,successor_quantity,strike_cash_amount,reviewed_at,review_source
```

Rules:

- `event_type`: `ASSIGNMENT`, `EXERCISE`, or `EXPIRATION`.
- `evidence_status`: exactly `approved`.
- `effective_at` and `reviewed_at`: timezone-bearing ISO-8601 values.
- predecessor fill IDs: non-empty JSON array in exact FIFO order.
- source event-leg IDs: non-empty JSON array linked to the event header.
- assignment/exercise successor fields are explicit and must reconcile to the
  broker deliverable; expiration successor fields remain empty.
- costs and quantities are finite decimals; no default multiplier or
  deliverable is inferred.

The file is operator input and can contain account and financial lineage. Keep
it outside Git unless it is a fully synthetic fixture.

## Safe workflow

1. Confirm the repository working tree and intended database path.
2. Create and validate a backup or isolated temporary database copy.
3. Run without `--apply` and inspect counts and all instruction evidence.
4. Run journal health and reconciliation on the same temporary database.
5. Obtain separate approval for an apply against the intended database.
6. Run with `--apply`; record the calculation run ID.
7. Re-run health, reconciliation, and dashboard contract validation.

Example dry-run:

```bash
PYTHONPATH=.:src ./.venv/bin/python3 scripts/journal/rebuild_pnl_allocations.py \
  --db /path/to/temporary-journal.duckdb \
  --asof 2026-07-17 \
  --instructions /private/path/reviewed-lifecycle-instructions.csv
```

Add `--apply` only after reviewing the dry-run and approving the database write.

## Failure and correction behavior

- Missing/mismatched event, leg, fill, account, currency, instrument, timestamp,
  quantity, direction, or FIFO order fails before writing.
- An existing event approval can be replayed identically. A conflicting
  reapproval is rejected; corrections require a separately linked corrective
  event rather than overwriting history.
- A dashboard or reconciliation check accepts a P&L run only when the current
  fill and approved-event fingerprints exactly match the persisted run.
- A replacement import is rejected after approved lifecycle/P&L history exists,
  preventing orphaned lineage.

Rollback is non-destructive: do not delete a calculation run. Correct the
reviewed input or calculation through a new approved event/version and append a
new run. Restore a verified pre-write backup only under the migration recovery
procedure.
