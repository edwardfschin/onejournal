# Schwab positions JSON adapter contract

## Scope

`schwab-position-json-v1` is the credential-free PNL-03 intake boundary for an
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
Schwab `EQUITY`. Listed options must declare Schwab `OPTION` and match the
mapped underlying, expiration, call/put right, and decimal strike. Contract
multiplier and currency remain explicit canonical mapping fields; they are not
inferred from a display symbol.

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
The initial field compatibility is therefore tested synthetically against the
response shape already consumed by the repository's isolated legacy position
readers. Bounded real evidence must confirm the shape before PNL-03 acceptance;
the adapter fails closed rather than adding aliases or inferred fallbacks.

ADR-0020 and `schwab-read-only-single-account-positions.v1` now provide the
offline external-acquisition boundary needed to carry one exact private
response into this adapter without giving OneJournal credential capability.
The canonical manifest contains only a safe endpoint template and account-hash
digest; the raw hash, expected account number, and complete symbol mapping are
separate owner-only conversion inputs. Synthetic profile and conversion tests
pass. No provider capture, private materialization, or real compatibility
acceptance has yet occurred.

PNL-03H adds a separate validation-only operator that reads an existing `0700`
bundle and `0600` private binding without creating any evidence or database
state. It emits only digest/count-based audit fields. Its validation result is
not a broker capture or financial acceptance.
