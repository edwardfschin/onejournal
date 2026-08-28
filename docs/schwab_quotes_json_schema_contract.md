# Schwab quote JSON adapter and evidence-import contract

## Status

PNL-02A and the interim one-app quote evidence bridge are implemented. A bounded
one-symbol official Schwab response was captured, transferred privately, and
validated on 2026-08-27. During this bounded step, OneBot/VPS is the temporary single
owner of the Schwab application and refreshable token for quote capture. The
current OneJournal quote path is credential-free and cannot call Schwab.

This is not the target provider architecture. The target makes OneJournal the
only project that owns approved provider connections and uses isolated Schwab,
IBKR, Moomoo, or later provider connectors behind the same broker-independent
quote contract. That integration plane and its Schwab cutover are not yet
implemented or approved.

This status means:

- the Schwab adapter is covered by a deliberately minimal synthetic example and
  a sanitized official-shape fixture with all symbol and price values replaced;
- OneJournal verifies and normalizes only a transferred, versioned private
  evidence bundle produced by OneBot;
- the verified bundle is adapted into OneJournal's provider-neutral capture
  envelope, which binds request identity, source checksum/locator, quote and
  receipt times, New York market date, and the repository freshness policy;
- tests prove the local fail-closed boundary and temporary-DuckDB persistence
  contract without credentials, network, provider calls, or private live
  evidence; the Schwab evidence operator itself still performs no database
  write; and
- the bounded response reported real-time entitlement and supplied bid, ask,
  last, quote time, and normal security status, but supplied no market-session
  field; OneJournal therefore preserved session as `unknown` and disallowed
  valuation; and
- this bounded evidence does not establish licensing, durable ingestion,
  production readiness, or end-to-end PNL-02 acceptance.

Schwab's authenticated Trader API specification remains the authoritative
provider contract:
<https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production>.
`quotes_official_sanitized_no_session.json` is structurally derived from the
bounded official response. It contains fictional symbol and price values,
omits unused provider fields, and deliberately preserves the observed absence
of `marketSession`. The private raw response remains outside Git.

## Explicit identity input

The adapter requires the caller to supply the exact Schwab symbol, OneJournal
`instrument_key`, asset class (`stock` or `option`), three-letter currency,
opaque connection UID, market date, and freshness-evaluation time. It does not
infer currency, option identity, account identity, provider fallback, market
session, or an instrument mapping.

The response must contain exactly the requested symbol set. Missing or
unexpected symbols reject the whole batch.

## Provider-field mapping

| Schwab field | OneJournal meaning | Failure behavior |
|---|---|---|
| top-level symbol key and `symbol` | provider and normalized symbol identity | Both must match the explicit request |
| `assetMainType` | `stock` or `option` | Unsupported or request-mismatched classes reject |
| `quote.bidPrice`, `askPrice`, `lastPrice` | exact-decimal top-of-book values | Floats, negatives, non-finite values, empty prices, and crossed bid/ask reject |
| `quote.quoteTime` | provider quote time in integer epoch milliseconds | Missing, fractional, negative, or invalid values reject |
| `realtime` | `real_time`/`entitled` or `delayed`/`delayed` | Missing or non-boolean values reject |
| `quote.marketSession` or top-level `marketSession` | explicit market session | Missing becomes `unknown`; unsupported values reject |
| `quote.securityStatus` | safety status | A present value other than `Normal` rejects |

The bounded official response confirmed the listed identity, asset, price,
quote-time, real-time, and security-status mappings. It did not supply
`marketSession`. The owner has selected Schwab-native market-hours or schedule
evidence from the same connected Schwab boundary as the exclusive resolver
source for this quote. The current provider-neutral `v1` authority object is not
sufficient because it lacks provider/connection binding and requires a MIC; the
versioned replacement and acceptance matrix are defined in
`docs/provider_native_market_session_contract.md` but are not yet implemented
or wired to this importer. Actual matching Schwab authority evidence therefore
remains required before this capture can become freshness-eligible. The adapter
and importer must not infer session from retrieval time, use another broker or
external calendar, or weaken the fail-closed contract.

## Interim one-app evidence bridge

For the current bounded evidence step, OneBot's guarded exporter is the only
component permitted to own or read the Schwab token for quote retrieval. It can
produce one private bundle containing exactly:

```text
<capture-id>/
  quote-response.json
  capture-v1.json
```

The OneBot manifest schema is
`onebot.schwab.quote-evidence-capture.v1`. It binds exact response bytes to the
approved request, terms acknowledgement, one-symbol GET, market date, clean
OneBot commit, timestamps, hash, and zero refresh/account/order/database counts.
The exporter contract disables redirects, retries, and OAuth refresh.

Transfer into `/Users/edward/Projects/Private/OneJournal` requires a later,
separate approval. Tokens, secrets, account identifiers, and provider
configuration are never transferred.

At the approved target cutover, OneBot's Schwab access is retired before the
isolated OneJournal Schwab connector becomes token owner. The two projects must
not refresh the same token lifecycle. Equivalent IBKR, Moomoo, and later
connectors must preserve this contract's provider-independent identity,
entitlement, raw-lineage, and freshness boundaries.

## Credential-free import

`scripts/journal/import_schwab_quote_evidence.py` performs no plan, capture, or
provider operation. It reads an explicitly selected bundle below an explicit
private vault root and fails closed unless:

- the vault and bundle are non-symlink `0700` directories;
- the bundle contains exactly the two contract files, both non-symlink `0600`;
- the schema, approval, terms acknowledgement, connection UID, symbol, market
  date, OneBot commit, endpoint, query, request count, and no-refresh controls
  exactly match explicit arguments;
- the raw byte count and SHA-256 match the manifest;
- the response is a finite JSON object containing exactly the approved symbol;
  and
- the existing Schwab adapter and freshness contract accept the evidence.

The operator emits only a secret-free summary. It does not write private
evidence, normalized files, DuckDB, migrations, caches, or generated output.
The normalized quote's current repository-shaped `raw_path` is an in-memory
logical locator under `data/raw/schwab/external/<capture-id>/`; no normalized
quote is persisted by this operator. The provider-neutral capture envelope now
retains the actual raw file as a safe path relative to the approved private-vault
root and binds it to the same SHA-256. A future approved ingestion operator may
persist that envelope through the common repository; this temporary OneBot-edge
operator does not become the target provider connector.

## Validation boundary

Tests establish exact-decimal mapping, identity and symbol scope,
manifest/schema/hash/mode/provenance enforcement, explicit freshness
evaluation, provider-neutral capture validation, temporary-DuckDB atomic replay,
zero evidence writes by the Schwab importer, and absence of credential, network,
refresh, account, and order capabilities in OneJournal.

The bounded capture establishes compatibility for the observed equity response,
provider-reported real-time entitlement, and actual private-vault transfer
integrity. The repository session-authority boundary is validated with synthetic
contract fixtures only. The capture does not establish a resolver output,
options compatibility, licensing, valuation eligibility, production readiness,
durable quote storage, or PNL-02 completion.

The current active OneJournal runtime is credential-free: the former ad hoc
Schwab raw-history credential operators have been retired. That retirement does
not prohibit the future isolated provider-integration service. Credentialed
code retained under legacy directories remains non-runtime historical source
and is not approved for reuse in that service.
