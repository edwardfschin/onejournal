# Schwab position-evidence intake operator

## Scope

`scripts/journal/validate_external_schwab_position_acquisition.py` validates
one already transferred
`schwab-read-only-single-account-positions.v1` bundle. It is the PNL-03H
owner-only, credential-free, validation-only boundary. It does not call Schwab,
access or refresh a credential, write private evidence, create or modify a
database, materialize a capture, schedule work, listen for requests,
synchronize, deploy, or calculate financial values.

It is not the OneBot/VPS capture producer. It is not an approval for provider
access or a private-evidence transfer.

## Required existing private inputs

All inputs are absolute, non-symlink paths. The acquisition root must already
be `0700`; every file below must already be `0600`.

1. Acquisition root containing exactly `acquisition-manifest.json` and the one
   response filename declared in it.
2. The active provider-use acknowledgement artifact.
3. A private canonical
   `onejournal.schwab-position-private-binding.v1` file containing the raw
   account hash, expected provider account number, opaque OneJournal account
   scope, and exact provider-symbol to canonical-instrument mappings.

The private binding is not created by this operator. Creating, transferring,
or retaining it requires a separate approval and stays outside Git. Its raw
identifiers must never appear in shell arguments, normal logs, frontend data,
or repository files.

## Validation sequence

The operator verifies, in order:

1. private path type, permissions, size limits, bundle membership, and no
   symlinks;
2. canonical external manifest, expected run/approval/owner/owner-epoch,
   acknowledgement authorization, exact response checksums, and the approved
   position profile;
3. canonical private binding and connection equality;
4. manifest account-hash digest against the in-memory private hash;
5. exact response account number, complete `positions` member, explicit
   mappings, identity terms, and decimal quantity semantics through
   `schwab-position-json-v2`.

Any failure stops before an audit result. The operator never treats a missing
positions member as an empty account and never infers an identity or mapping.

## Output

The only stdout artifact is one compact JSON audit with:

- acquisition-run and manifest digests;
- private-binding digest, not its content;
- provider and opaque connection identity;
- hash of the OneJournal account scope, not the scope itself;
- broker snapshot UID, raw-response digest, market date, retrieval instant,
  complete-account flag, position count, and final validation status.

It emits no raw account hash, provider account number, provider symbol,
position, cost basis, market value, P&L, response body, mapping, credential, or
private path.

`validated_external_position_unmaterialized` means only that the exact input
bundle passed this boundary. It does not establish broker compatibility,
complete fill/lifecycle history, reconciliation, a valuation mark, financial
acceptance, PNL-03 completion, WEB-W07 availability, or production readiness.

## Invocation shape

Use the project interpreter and provide only private absolute paths:

```text
.venv/bin/python scripts/journal/validate_external_schwab_position_acquisition.py \
  --acquisition-root /absolute/private/acquisition-root \
  --acknowledgement /absolute/private/provider-usage-acknowledgement.json \
  --position-binding /absolute/private/position-binding.json \
  --expected-run-uid <approved-run-uid> \
  --expected-approval-id <approved-approval-id> \
  --expected-owner-uid <approved-owner-uid> \
  --expected-owner-epoch-uid <approved-owner-epoch-uid> \
  --evaluated-at <UTC-instant>
```

Do not place any raw account identifier in shell history or shared logs. The
binding file is the sole private identifier input.

## Next approval gates

PNL-03H does not authorize:

- a OneBot/VPS provider call or token refresh;
- private-binding creation, evidence capture, or transfer;
- private materialization or DuckDB write/read-back;
- quote/session capture needed for valuation;
- complete fill/lifecycle reconciliation;
- API/frontend wiring, production migration, commit, push, sync, or deployment.

Each is independently approved only after the operator and its exact audit
scope are accepted.
