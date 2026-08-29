# Schwab quote JSON adapter and evidence-import contract

## Status

PNL-02A and the interim one-app quote evidence bridge are implemented. The
bounded `PNL-02-T14-SCHWAB-20260829-06` capture was transferred privately and
validated on 2026-08-29. It contains same-date official equity, listed-option,
and normal-session schedule evidence for 2026-08-28 plus approved closed and
shortened-session schedules. During this bounded step, OneBot/VPS remains the
temporary single owner of the Schwab application and refreshable token. The
current OneJournal path is credential-free and cannot call Schwab.

This is not the target provider architecture. The target makes OneJournal the
only project that owns approved provider connections and uses isolated Schwab,
IBKR, Moomoo, or later provider connectors behind the same broker-independent
quote contract. That integration plane and its Schwab cutover are not yet
implemented or approved.

This status means:

- `schwab-quote-json-v2` accepts the exact private equity and listed-option
  response shapes without logging or copying their prices into Git;
- `schwab-market-hours-json-v1` losslessly parses the exact private normal,
  closed-sentinel, and shortened-session response shapes;
- OneJournal verifies and normalizes only a transferred, versioned private
  evidence bundle produced by OneBot;
- the verified bundle is adapted into OneJournal's provider-neutral capture
  envelope, which binds request identity, source checksum/locator, quote and
  receipt times, New York market date, and the repository freshness policy;
- tests prove the local fail-closed boundary and temporary-DuckDB persistence
  contract without credentials, network, provider calls, or private live
  evidence; the Schwab evidence operator itself still performs no database
  write; and
- both bounded quote responses reported real-time entitlement and supplied bid,
  ask, last, and quote time, but supplied no market-session field; the option
  reported `securityStatus=Normal`, while the after-hours equity response
  reported `securityStatus=Closed`; `Closed` becomes provider-neutral
  `data_mode=frozen` while its session stays `unknown` until exact matching
  provider-native authority exists; and
- the market-hours evidence supplies exact offset-aware phase intervals and a
  market-level `isOpen=false` sentinel, but no IANA timezone identifier and no
  provider label distinguishing holiday from another closed-day reason; and
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

The status correction is emitted as `schwab-quote-json-v2` so lineage never
silently reinterprets a v1 result. No real quote was persisted under v1, so no
journal migration or rewrite is required. Historical v1 evidence remains
immutable and is not relabelled.

## Provider-field mapping

| Schwab field | OneJournal meaning | Failure behavior |
|---|---|---|
| top-level symbol key and `symbol` | provider and normalized symbol identity | Both must match the explicit request |
| `assetMainType` | `stock` or `option` | Unsupported or request-mismatched classes reject |
| `quote.bidPrice`, `askPrice`, `lastPrice` | exact-decimal top-of-book values | Floats, negatives, non-finite values, empty prices, and crossed bid/ask reject |
| `quote.quoteTime` | provider quote time in integer epoch milliseconds | Missing, fractional, negative, or invalid values reject |
| `realtime` | `real_time`/`entitled` or `delayed`/`delayed` | Missing or non-boolean values reject |
| `quote.marketSession` or top-level `marketSession` | explicit market session | Missing becomes `unknown`; unsupported values reject |
| `quote.securityStatus` | provider security state | `Normal` preserves the entitlement-derived data mode; `Closed` becomes `frozen` and forces session to `unknown`; missing remains supported; `Halted` and every other value reject |

The bounded official responses confirmed the listed identity, stock/option,
price, quote-time, real-time, and security-status mappings. Neither quote
supplied `marketSession`. `securityStatus=Closed` is not treated as schedule
evidence: it preserves provider entitlement, changes only `data_mode` to
`frozen`, and remains valuation-ineligible until exact v2 authority resolves
the quote and evaluation sessions. The owner has selected Schwab-native market-hours or
schedule evidence from the same connected Schwab boundary as the exclusive
resolver source. The legacy provider-neutral `v1` authority object is not
sufficient because it lacks provider/connection binding and requires a MIC.
`onejournal.provider-market-session-authority.v2` supplies the exact provider/
connection/quote/instrument/schedule/source boundary, and the importer can
consume it only through an injected credential-free resolver.

`src/onejournal/brokers/schwab/market_hours_json.py` is the concrete,
credential-free payload adapter. It validates the exact equity/option scope,
product identity, requested date, open state, provider session names,
offset-aware increasing intervals, and the observed exact closed-market
sentinel. It deliberately stops before producing a v2 authority value because
the raw response itself does not name an IANA timezone or distinguish a holiday
from another provider-confirmed closed date. The owner-approved
`schwab-market-hours-resolver-v1` adds only the explicit `EQ`/`EQO`/`IND` to
`America/New_York` scope mapping, rejects response offsets that conflict with
that zone, classifies shortened phases against a checksum-bound normal response,
and preserves unnamed closure as `closed_unspecified`. Its v2 lineage points to
the combined manifest that binds every schedule member used. Capture `-06`
provides a 2026-08-28 normal schedule matching both quote dates. The listed
option produces actual combined v2 authority directly. The equity produces the
same authority only through `schwab-quote-json-v2`; without that authority its
frozen, session-unknown quote remains unavailable. The adapter and importer must
not substitute retrieval time, another broker, an external calendar, or an
unapproved label.

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

The versioned summary schema is now
`onejournal.schwab.quote-evidence-import-summary.v2`. It adds quote/evaluation
session-source labels and nullable provider-session authority contract/UID
fields. It contains no schedule raw path, payload, account identifier, or
credential. With no injected resolver, those authority fields remain null and
the existing quote-only behavior remains fail closed when session is unknown.

## Validation boundary

Tests establish exact-decimal mapping, identity and symbol scope,
manifest/schema/hash/mode/provenance enforcement, explicit freshness
evaluation, provider-neutral capture validation, temporary-DuckDB atomic replay,
zero evidence writes by the Schwab importer, and absence of credential, network,
refresh, account, and order capabilities in OneJournal.

Capture `-06` establishes compatibility for the observed equity and
listed-option responses, provider-reported real-time entitlement, exact normal/
closed/shortened market-hours payloads, private-vault transfer integrity, and
same-date combined v2 authority. Read-only private-byte review proves the option
as `market_closed_last`; after the v2 adapter correction, the equity `Closed`
state becomes frozen and is valuation-eligible only when exact v2 authority
reports the evaluation session closed. Synthetic tests prove the same frozen
quote is not valuation-eligible while the effective market remains open. This
does not establish production readiness, durable quote storage, T15 cutover, or
end-to-end PNL-02 acceptance.

The current active OneJournal runtime is credential-free: the former ad hoc
Schwab raw-history credential operators have been retired. That retirement does
not prohibit the future isolated provider-integration service. Credentialed
code retained under legacy directories remains non-runtime historical source
and is not approved for reuse in that service.
