# Schwab lifecycle evidence intake operator

## Purpose

`scripts/journal/validate_external_schwab_lifecycle_acquisition.py` validates
one pre-existing `schwab-read-only-single-account-lifecycle.v1` bundle. It is a
credential-free, validation-only PNL-03L boundary.

It reads exact private provider bytes, verifies the external acquisition and an
owner-private account binding, converts order and transaction evidence through
OneJournal adapters in memory, and emits only privacy-safe counts and digests.

## Required private inputs

- an existing absolute `0700` acquisition directory containing exactly:
  - `acquisition-manifest.json` (`0600`);
  - the manifest-named order response (`0600`); and
  - the manifest-named transaction response (`0600`);
- the exact active provider-use acknowledgement (`0600`); and
- one canonical `onejournal.schwab-account-private-binding.v1` file (`0600`).

The private account binding contains the provider account hash and account
number. It must remain outside Git, logs, frontend payloads, generated output,
and ordinary audit records.

## Validation-only command shape

```text
PYTHONPATH=.:src .venv/bin/python \
  scripts/journal/validate_external_schwab_lifecycle_acquisition.py \
  --acquisition-root /absolute/private/acquisition/root \
  --acknowledgement /absolute/private/provider-usage-acknowledgement.json \
  --account-binding /absolute/private/private-account-binding.json \
  --expected-run-uid <approved-run-uid> \
  --expected-approval-id <approved-approval-id> \
  --expected-owner-uid <approved-owner-uid> \
  --expected-owner-epoch-uid <approved-owner-epoch-uid> \
  --evaluated-at <ISO-8601 timestamp with timezone>
```

## Output

The single JSON audit contains only acquisition and binding digests, provider
and opaque connection identity, a digest of the opaque OneJournal account ID,
window dates, order/transaction/fill/lifecycle counts, every out-of-window
raw-order/fill/event/leg exclusion count, currency-consensus code and
provenance counts, reconciliation counts, and final validation status. It
never prints provider account identifiers, symbols, quantities, prices, raw
response content, credentials, or paths.

Top-level order membership uses entry, close, and recursive execution evidence.
Every raw order record first passes exact account and timestamp validation.
Valid non-intersecting top-level records are preserved in raw evidence but
excluded and counted before normalization; malformed, undated, or
account-mismatched records remain fail-closed.
After conversion, order and transaction fills use only their exact execution
timestamps; lifecycle events and their corresponding legs use only the exact
event timestamp. A record-level query match therefore cannot admit a row from
an adjacent date, and exclusions remain visible rather than silently dropped.

Currency consensus is available only after same-account/window validation and
only when eligible valid trade records contain one conflict-free explicit
provider currency code. The audit's explicit-item and resolved-record counts
make that use visible. Zero or conflicting codes fail closed when a trade lacks
its own currency leg; no Schwab-wide USD default exists.

`reconciliation_status=exact` means normalized order and transaction fill rows
match inside this bundle. `pending` preserves unmatched evidence. Neither state
proves complete account history, current position coverage, PNL-03 acceptance,
or financial correctness across other windows.

## Safety and later gates

The operator has no provider client, credential, refresh, account discovery,
order mutation, filesystem-write, database, migration, scheduler, listener,
sync, or deployment capability. It cannot create the private account binding or
evidence bundle.

Provider capture, private binding creation, transfer, append-only
materialization, journal import, and owner financial acceptance remain separate
explicit approvals. PNL-03N implements cross-window assembly as a pure,
credential-free, non-writing boundary documented in
`docs/current_position_lifecycle_coverage_contract.md`; using additional real
windows still requires separately approved acquisition and transfer.
