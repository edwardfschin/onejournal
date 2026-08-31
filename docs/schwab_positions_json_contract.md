# Schwab positions JSON adapter contract

## Scope

`schwab-position-json-v2` is the credential-free PNL-03 intake boundary for an
already captured Schwab single-account response. It cannot call Schwab, access
or refresh credentials, discover accounts, place orders, write private
evidence, or write a database.

The adapter requires an exact successful `GET` to the allowlisted Schwab
single-account endpoint with exactly `fields=positions`, one attempt, no
redirect, JSON content, a bound account-hash digest, an exact provider account
number, exact response checksum, explicit OneJournal account/connection scope,
retrieval instant, New York market date, and source locator. Only that bounded
request plus an explicit `securitiesAccount.positions` list can assert account
completeness. A missing positions member is not an empty account.

## Identity and quantity

Every returned provider symbol must have exactly one explicit
`onejournal.instrument-identity.v1` mapping, and every mapping must be consumed.
Provider symbols are lineage, not canonical identity. Equities must declare
Schwab `EQUITY`, except that Schwab `COLLECTIVE_INVESTMENT` is accepted as the
existing canonical equity class only when its provider `type` is exactly
`EXCHANGE_TRADED_FUND`. Other collective-investment types remain unsupported.
Listed options must declare Schwab `OPTION`; their provider symbol must be an
exact 21-character OCC symbol whose root, expiration, call/put right, and
thousandths-encoded strike all match the explicit mapping. If Schwab also
supplies `uniformSymbol`, `expirationDate`, or `strikePrice`, each supplied
field must agree. Contract multiplier and currency remain explicit canonical
mapping fields; OCC parsing verifies the mapping and never creates it.

Signed quantity is exact `longQuantity - shortQuantity`. Missing, float,
negative, simultaneous non-zero long/short, or zero position rows fail closed.
Broker average price, market value, and direction-appropriate open P&L are
preserved as reconciliation evidence and never override OneJournal FIFO cost
basis or valuation.

## Output and limitations

The result is one deterministic, complete-account `BrokerPositionSnapshot`
with exact raw lineage and zero or more broker position records. The adapter
does not calculate cost basis, select a mark, reconcile fills, or establish
financial acceptance. Real provider evidence acquisition, private
materialization, production migration, and owner acceptance remain separate
approval gates.

Current official Schwab account specification content is sign-in restricted.
An approved bounded source-host capture on 2026-08-31 established that the
observed option rows use exact 21-character OCC `symbol`/`uniformSymbol` values
without separate expiration or strike fields, and that an observed ETF uses
`COLLECTIVE_INVESTMENT` with `EXCHANGE_TRADED_FUND`. No provider bytes or
account identifiers enter this repository. Focused synthetic fixtures encode
only those field-shape facts. Unsupported collective types, malformed OCC
symbols, mismatched explicit mappings, and conflicting optional fields fail
closed.

Version 2 supersedes the synthetic-only v1 option-field assumption. The
version change preserves deterministic replay lineage because a payload that
v1 rejected can now be accepted only under these stricter explicit-mapping and
OCC-verification rules.

ADR-0020 and `schwab-read-only-single-account-positions.v1` now provide the
offline external-acquisition boundary needed to carry one exact private
response into this adapter without giving OneJournal credential capability.
The canonical manifest contains only a safe endpoint template and account-hash
digest; the raw hash, expected account number, and complete symbol mapping are
separate owner-only conversion inputs. Synthetic profile and conversion tests
pass. The bounded source capture exists only in its owner-private source
location; no transfer, private binding, OneJournal validation, materialization,
reconciliation, or financial acceptance has occurred.

PNL-03H adds a separate validation-only operator that reads an existing `0700`
bundle and `0600` private binding without creating any evidence or database
state. It emits only digest/count-based audit fields. Its validation result is
not a broker capture or financial acceptance.
