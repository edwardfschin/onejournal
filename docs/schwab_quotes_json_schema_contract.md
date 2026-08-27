# Schwab quote JSON adapter and capture contract

## Status

PNL-02A is implemented and validated offline.

This status means:

- the Schwab quote adapter is covered by a deliberately minimal synthetic JSON
  example;
- the capture operator defaults to plan-only and has no account, order,
  database, migration, or background-polling capability;
- tests prove the local fail-closed boundaries without reading credentials or
  calling Schwab; and
- no official Schwab quote payload, live entitlement result, raw provider
  capture, or end-to-end PNL-02 acceptance evidence exists yet.

Schwab's authenticated Trader API specification remains the authoritative
provider contract:
<https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production>.
The synthetic example under `docs/examples/schwab_quotes_json/` is not an
official response fixture and cannot establish provider compatibility.

## Explicit identity input

The adapter requires the caller to supply all of the following for each quote:

- exact Schwab provider symbol;
- exact OneJournal `instrument_key`;
- OneJournal asset class (`stock` or `option`);
- three-letter currency; and
- opaque local `connection_uid`.

It does not infer currency, option identity, account identity, provider
fallback, or an instrument mapping from the response. The response must contain
exactly the requested symbol set. Missing or unexpected symbols reject the
whole batch.

## Provider-field mapping

The offline adapter currently recognizes this minimal field boundary:

| Schwab field | OneJournal meaning | Failure behavior |
|---|---|---|
| top-level symbol key and `symbol` | `provider_instrument_id` and symbol identity | Both must match the explicit request |
| `assetMainType` | `stock` or `option` | Unsupported or request-mismatched classes reject |
| `quote.bidPrice`, `askPrice`, `lastPrice` | exact-decimal top-of-book values | Floats, negatives, non-finite values, empty prices, and crossed bid/ask reject |
| `quote.quoteTime` | provider quote time in integer epoch milliseconds | Missing, fractional, negative, or invalid values reject |
| `realtime` | `real_time`/`entitled` or `delayed`/`delayed` | Missing or non-boolean values reject |
| `quote.marketSession` or top-level `marketSession` | explicit market session | Missing becomes `unknown`; unsupported values reject |
| `quote.securityStatus` | safety status | A present value other than `Normal` rejects |

An absent provider-declared market session is not inferred from local time.
The normalized quote is retained as `unknown`, and the existing freshness gate
makes it unavailable for valuation.

These mappings remain provisional until checked against a sanitized official
Schwab response. PNL-02B may correct or extend the adapter if the official
payload differs; it must not weaken the fail-closed contract.

## Guarded capture operator

`scripts/journal/fetch_schwab_quote.py` is intentionally limited to one symbol
and the exact production endpoint:

```text
GET https://api.schwabapi.com/marketdata/v1/quotes
```

The request includes only `symbols=<one symbol>` and
`fields=quote,reference`. Redirects are disabled. Response bodies larger than
5 MiB, non-JSON responses, non-object responses, and HTTP failures reject.
HTTP error bodies are not printed.

Without `--execute-read-only`, the operator is plan-only. Plan-only mode does
not read a token, create a lock, make a network request, or write a file.

A future execution requires all of these gates:

- separate owner approval for the exact call;
- `--execute-read-only`;
- a non-empty approval identifier;
- a non-empty provider-terms acknowledgement identifier;
- the exact full repository commit approved for the call and a clean working
  tree at that commit;
- an explicit symbol, instrument key, asset class, currency, market date, and
  connection UID;
- OneJournal-scoped Schwab configuration; and
- an existing, non-symlinked, owner-readable token file with no group or other
  permissions; and
- the exact Schwab production API base.

The operator exposes no account hash argument and no account or order method.
Its provider-access lock serializes quote capture with the guarded raw-history
backfill operator so both cannot refresh the same token concurrently.
It captures the exact successful response bytes atomically under
`data/raw/schwab/<market-date>/quotes/`, with a `0700` leaf directory and `0600`
file. It refuses overwrite, records SHA-256, normalizes in memory, assesses
freshness in memory, and writes a private `capture-v1` sidecar binding the raw
hash to the approval, terms-acknowledgement, request identity, adapter version,
quote identity, repository commit, pre-call clean-tree state, and freshness
result. It never opens DuckDB. The sidecar binds an acknowledgement identifier;
it is not itself a production user-acceptance record.

OAuth token refresh can occur during a separately approved execution when the
existing OneJournal-scoped token requires it. That credential access and token
write are not part of PNL-02A and require the later provider-call approval.

## Validation boundary

PNL-02A tests establish:

- exact explicit identity mapping;
- exact-decimal parsing from captured response bytes;
- full-batch rejection on missing or unexpected symbols;
- fail-closed asset class, status, delay, session, price, timestamp, and raw
  lineage behavior;
- plan-only operation before credential or file access;
- exact one-endpoint GET construction with redirects disabled;
- suppression of HTTP response bodies in errors;
- exact-byte private raw capture in a temporary test directory; and
- private capture-manifest lineage with safe machine identifiers; and
- exact approved repository-commit and clean-worktree provenance; and
- zero DuckDB writes.

They do not establish current Schwab schema compatibility, market-data
entitlement, live freshness, provider terms compliance, production readiness,
or PNL-02 completion.
