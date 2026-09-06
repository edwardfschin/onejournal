# Schwab Phase 1 execution-first journal projection

## Purpose

`onejournal.phase1-journal-execution-projection.v1` corrects the semantic gap
between broker executions and journal trade structure. Schwab can report one
order as several distinct execution activities. Those activities are source
evidence, not duplicate strategy legs, and must never be deleted merely because
their economic fields look alike.

The projection consumes one exact migration-0018 materialization and its
persisted Phase 1 transaction family. It makes no provider call and does not
change the accepted assembly, normalized fills, migration-0018 rows, journal
entries, reviews, or API audit history.

## Model

The projection preserves three separate concepts:

1. **Execution** — one immutable Schwab transaction activity and normalized
   fill. Every execution has a stable opaque identity and remains independently
   traceable.
2. **Instrument** — one canonical equity or option contract. Several partial
   executions of the same instrument are summarized together without losing
   the individual records.
3. **Trade lifecycle** — one opening-through-closing episode. Its strategy is
   classified from distinct instruments and the opening direction, never from
   the number of execution rows.

A single option contract bought and later sold is therefore one buy-option
lifecycle, not a two-leg vertical. A specific vertical label requires two
distinct option contracts, explicit upstream grouping, matching underlying,
expiry and option type, distinct strikes, and opposing opening directions.
Anything less remains generically multi-instrument rather than receiving a
fabricated strategy name.

## Financial reconciliation

For every execution the projection calculates:

```text
SELL: quantity * fill price * multiplier - commission - fees
BUY : -(quantity * fill price * multiplier) - commission - fees
```

The result must equal the exact Schwab transaction `net_amount`. A missing,
ambiguous, or unequal transaction fails the complete projection before any
write. The projected value is called **net cash movement**, never P&L. Earlier
history remains necessary for transferred positions and other
`history_extension_required` lifecycles; their episode-level financial
aggregates remain unavailable.

## Persistence and operation

Migration 0019 adds one projection run plus episode, instrument and execution
projection tables. The operator requires an exact materialization identity:

```bash
python scripts/journal/project_schwab_phase1_executions.py \
  --db /absolute/private/mode-0600.duckdb \
  --materialization-uid schwab-phase1-journal-materialization:<sha256>
```

There is no implicit latest-run selection. The write is atomic and identical
replay verifies every projected row. The operator output contains identities,
fingerprints and counts only—not symbols, account identifiers or financial
values.

Before applying migration 0019 to an operational database, create and checksum
a mode-`0600` backup, rehearse migration/projection/replay/integrity on a
disposable copy, then obtain explicit owner approval. Rollback stops the local
API and restores that exact backup.
