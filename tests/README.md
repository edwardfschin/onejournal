# OneJournal Automated Tests

## Purpose

The initial test suite locks the behavior that is implemented and validated
today. It does not imply that preview trade grouping is the final lifecycle or
that gross cashflow is P&L.

The suite uses Python's standard-library `unittest` runner to keep the early
foundation simple and dependency-free.

## Test layers

- Unit: manual CSV parsing, episode grouping/classification, and dashboard
  payload construction.
- Lifecycle contract: partial fill events and partial close behavior.
- Financial contract: versioned FIFO closed-lot allocations, source-fill
  lineage, quantities, multipliers, commission/fee allocation, realized P&L,
  open cost basis, marks, assignment/exercise/expiration transformations,
  input fingerprints, durable allocation lineage, and fail-closed incomplete
  evidence.
- Adapter contract: deterministic Schwab orders/transactions normalization,
  including lifecycle event headers, decimal-safe transfer-item evidence legs,
  missing-evidence markers, and no inferred lifecycle P&L.
- Market-data contract: provider-independent quote identity, private raw lineage,
  entitlement/delay/session state, deterministic freshness eligibility, and
  atomic/idempotent temporary-DuckDB persistence. The provider-neutral capture
  boundary also proves exact request/response identity, quote/receive/evaluation
  ordering, New York market date, repository-policy loading, safe source
  location, and full-envelope replay conflicts with Schwab and second-provider
  synthetic cases. PNL-02A adds Schwab quote mapping, including a sanitized
  official equity response shape whose absent market-session field must remain
  `unknown` and valuation-ineligible. The interim
  one-app evidence bridge makes OneBot the temporary single credential-owning
  capture producer and tests the current OneJournal runtime as a credential-free,
  read-only verifier/normalizer of a transferred two-file private bundle. This
  does not test or define the target OneJournal-owned multi-provider connector
  plane. PNL-02 T09 adds the versioned provider-native session authority and
  injected resolver boundary, proving exact same-provider/connection/quote/
  instrument/source binding, separate quote/evaluation phases, optional MIC,
  DST, regular/extended/closed/holiday/early-close/unscheduled-closure behavior,
  expiry, conflict, outage, and cross-provider failure. A credential-free
  importer test proves that matching injected authority can qualify a quote
  whose provider session is absent without writing evidence or a database.
  PNL-02 T14 adds a concrete credential-free Schwab market-hours payload parser.
  It proves exact equity/option product scope, offset-aware normal/extended and
  shortened-session intervals, the observed closed-market sentinel, and
  fail-closed malformed/overlapping/unsupported shapes. The approved offline
  resolver adds exact Schwab product scopes, IANA offset validation,
  `closed_unspecified`, normal-versus-shortened comparison, combined-manifest
  lineage, and exact-date resolution. `schwab-quote-json-v2` adds the observed
  `securityStatus=Closed` boundary: it produces a frozen quote with unknown
  session, remains unavailable without authority, remains stale while an
  effective session is open, and becomes `market_closed_last` only after exact
  v2 authority reports close. The official private `-06` equity, option, and
  market-hours bytes are checked separately outside the automated suite and are
  never copied into Git; both quote paths produce same-date combined authority.
  PNL-02 T11 adds the strict local-owner
  provider-use profile and deterministic connection-scoped acknowledgement
  boundary. It proves that missing, incomplete, superseded, scope-expanded, or
  tampered acknowledgements fail before retrieval; acknowledgement cannot
  replace provider-reported entitlement; and raw evidence cannot be scheduled
  for automatic or unaudited deletion. T12/T13 add the offline connector and
  restart-safe durable ingestion boundary: atomic private raw/manifest/envelope
  storage, checksum-bound recovery, exact approval scope, explicit write mode,
  required pre-applied migrations, transactional first-write/replay behavior,
  and exact-run semantic read-back on temporary DuckDB databases. No real
  acknowledgement, provider call, credential, private evidence, journal write,
  migration, or deletion is used. The T15 offline rehearsal contract validates
  the provider-neutral `source_active -> owner_gap ->
  target_provisioned_disabled -> target_active` sequence for forward cutover and
  rollback. It rejects dual ownership, reused owner or credential lineage, host
  collision, target exposure, phase/time disorder, and malformed evidence
  without performing any operational action. Mark selection is explicitly
  deferred to PNL-03 policy. The temporary Mac staging tests keep every checked-in
  capability disabled, use an injected fake Keychain runner, prove secrets do not
  enter command arguments or representations, enforce credential-generation and
  owner-epoch continuity, serialize a private local owner lease, and reject public
  listeners, DuckDB mounts, provider calls, refresh, or installation while disabled.
- Integration: schema initialization and migration, import, append-only journal
  history, review compatibility projection, replay preservation, DuckDB reads,
  and DB dashboard payload construction using a temporary database.
- Regression: invalid inputs, as-of mismatches, duplicate payload entries, and
  unsupported fill sides must fail explicitly; unallocated lifecycle events
  and stale/mismatched calculation runs must block publication-grade P&L
  status, while replace imports cannot orphan approved P&L history.
- Journal product: deterministic review queues, private structured entry
  history, search/filter/saved-view behavior, attachment fail-closed policy,
  process goals, habits, and explicit-period recurring review transitions.

Tests must not use the production journal database, private broker data, broker
APIs, or order APIs.

## Run

From the repository root with `PYTHONPATH=.:src` (or via `./bin/onejournal_ci.sh`):

```bash
PYTHONPATH=.:src python3 -m unittest discover -s tests -p "test_*.py" -v
```

The full baseline also runs this suite:

```bash
./bin/onejournal_ci.sh
```

The clean-checkout CI entry point also runs this suite together with dependency,
compilation, repository-safety, and fixture contract checks:

```bash
./bin/onejournal_ci.sh
```
