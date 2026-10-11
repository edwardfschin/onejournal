# Schwab Phase 1 evidence import contract

## Scope

P1-05 introduced the immutable v1, additive, credential-free import boundary for exact Schwab
evidence already converted by OneJournal. It supports one opaque account per
assembly and repeated assemblies for multiple owner-controlled accounts. It has
no provider, token, refresh, order, deployment, website, or automatic migration
capability.

Authoritative implementation:

- `src/onejournal/journal/schwab_evidence_assembly.py`;
- `src/onejournal/journal/schwab_evidence_import_repository.py`;
- migration `0016_add_phase1_schwab_evidence_assemblies.sql`; and
- `scripts/journal/ingest_schwab_phase1_evidence_assembly.py`.

## Source-to-family mapping

Assembly v1 contains the original eight families below. Assembly v2 preserves
those families in meaning and adds `lifecycle_events` and
`lifecycle_event_legs` from the already converted Schwab transactions. V2 is an
additive P1-06 correction; it does not supersede or rewrite the accepted v1 run.

| Family | Authoritative source | Rule |
|---|---|---|
| account | exact Schwab account-position response | Preserve observed account type and mapped current-balance fields; never invent labels, types, currency, or zero balances. |
| positions | complete Schwab position snapshot | Preserve canonical OneJournal instrument identity, signed quantity, and broker-observed basis/value/P&L fields. |
| orders | exact Schwab order responses | Preserve each parent and child order observation separately with its stable logical order ID, source-window observation ID, state, timing, requested quantities, and leg detail. Repeated logical orders may reflect state evolution and are not silently deduplicated. |
| transactions | exact Schwab transaction responses | Preserve each activity observation with its stable logical transaction ID, source-window observation ID, status, timing, net amount, and transfer-item detail. |
| fills | reconciled transaction fill rows | Transactions are authoritative after order/transaction comparison; unmatched evidence remains visible. |
| cash | exact Schwab transaction and transfer-item fields | Preserve each source-window observation plus `netAmount`, security `cost`, and currency/fee evidence as distinct source roles; do not aggregate them or call them P&L. |
| quotes | accepted normalized quote capture | Require its instruments to be a subset of the complete current-position set, preserve exact covered/uncovered counts, and retain immutable raw lineage. |
| sessions | same-provider session authority | Require exact quote binding, evaluation time, validity, and provider raw lineage. |
| lifecycle_events (v2) | normalized Schwab transaction lifecycle headers | Preserve stable event identity, event type/time, evidence status, source observation identity, and raw lineage. |
| lifecycle_event_legs (v2) | normalized Schwab transaction transfer-item legs | Preserve event relationship, canonical instrument fields, signed quantity, position effect, evidence status, and raw lineage. |

Provider account numbers and account hashes are in-memory binding inputs only.
They are not assembly fields, database values, or audit output. The opaque
`source_account_id` is stable within the owner's private system and scopes every
account-dependent family.

## Assembly gates

The builder rejects:

- missing or mismatched raw checksums;
- mixed provider, connection, opaque account, current market date, or currency;
- an incomplete position snapshot;
- missing direct account, order, or transaction evidence;
- gaps or overlaps in lifecycle windows;
- lifecycle evidence after the snapshot date;
- duplicate record identities;
- a quote for an instrument absent from the current position snapshot;
- missing, duplicate, expired, or cross-provider session authority;
- family count, exclusion, reconciliation, status, or fingerprint mismatch; and
- unsupported or non-finite financial value types.

All values use decimal-safe canonical JSON. Datetimes become explicit UTC
offset strings and dates become ISO dates before fingerprinting or persistence.
Decoded records are recursively immutable.

An assembly is `ready` only when order/transaction fill reconciliation is
exact, no fill row was excluded, and every retained cash row has explicit
currency evidence. Otherwise it is `review_required`. Either status preserves
evidence; only a separately approved downstream financial contract may decide
whether a bounded subset is usable.

Independent quote coverage is explicit rather than silently required to equal
the complete position count. `positions_without_quotes` must equal position
count minus quote count, and `all_positions_have_quotes` must agree with that
count. Every included quote still requires exact same-provider session
authority. Unquoted positions remain visible and unavailable to quote-dependent
consumers; a separately accepted broker-current route may use exact value
fields from the complete Schwab position response without inventing a quote.

## Persistence and replay

### Additive snapshot-cutoff assembly v3

The owner's 2026-10-11 offline correction approval adds
`onejournal.schwab-phase1-evidence-assembly.v3` and artifact v3. It retains the
ten-family v2 structure without changing v1/v2 serialization or fingerprints.
Its authoritative producer is `build_schwab_phase1_evidence_assembly_v3`.

V3 accepts one or two independent converted quote captures. Duplicate
instruments fail. Provider, connection, currency, position subset, exact raw
lineage, capture validation and same-provider session authority remain mandatory.
Quote `asof` remains its provider timestamp's New York date; it need not equal
the snapshot's New York date. Quotes later than the snapshot instant fail.
Evaluation time stays distinct; no timestamps are changed to fit the contract,
and no freshness rule is weakened.

`snapshot_cutoff_utc` must equal the complete account snapshot receipt instant;
its New York date must equal assembly `asof`. Contiguous history query dates
remain UTC dates and end on the cutoff's UTC date. Admitted transaction, fill,
cash and lifecycle-event instants must be no later than the exact cutoff;
lifecycle legs follow their parent event. Missing or naive instants fail.
Later records are excluded with `after_snapshot_cutoff` counts, retaining raw
source evidence and hashes. Account metadata separately counts later order
fill rows; direct order observations are retained for lineage, not treated as
snapshot-time execution state. Global order/transaction reconciliation is
recomputed after filtering. Any such financial exclusion makes v3
`review_required`. Historical exclusions remain separately labelled.

Migration 0027 adds only `phase1_schwab_snapshot_evidence_imports`. The private
canonical artifact retains all families, counts, exclusions and fingerprints.
SQL constraints distinguish UTC query dates from the New York snapshot date.
`schwab_snapshot_evidence_repository.py` requires a pre-existing database and
the exact applied migration checksum; write/replay/read-back validate both
artifact digest and duplicated scope metadata in one transaction. UTC cutoff
comparison uses exact integer microseconds, without adding a timezone package.
It never automatically migrates or activates a financial/report release.

Pure materialization, execution projection and lifecycle reconciliation consume
validated v3. The legacy history-revision writer rejects v3 before database
access because migration 0021 still binds v2 lineage and market-date window
constraints. A compatible history/report activation path remains outstanding;
evidence storage is not proof that the website refresh is wired in.

Live migration, private persistence and activation remain outside the offline
approval. Existing accepted reporting releases and all unresolved positions
are preserved. Copy-only upgrade and synthetic exact replay passed; actual
private v3 assembly/reconciliation still require quote/session evidence.

### Retained v1/v2 stores

Migration 0016 is additive:

- `phase1_schwab_evidence_import_runs` stores account/as-of scope,
  reconciliation, status, and the assembly fingerprint;
- `phase1_schwab_evidence_import_families` stores the exact eight family
  payloads, source digests, counts, exclusions, and family fingerprints.

The repository validates before opening the database, requires the database to
exist, checks migration 0016, and writes the run and all families in one
transaction. A failure rolls back. Identical replay creates no rows. Exact
read-back reconstructs and revalidates the assembly; callers cannot silently
fall back to another run.

Migration 0020 separately stores the ten-family assembly v2. Its exact event and
leg families support the lifecycle reconciliation contract without modifying
the v1 tables or acceptance evidence.

These private tables may contain holdings, symbols, balances, and transaction
evidence. They must never be committed, logged, returned by a public endpoint,
or copied into test fixtures. Ordinary audit exposes only hashes, counts, scope
date, reconciliation, and status.

## Validation and acceptance boundary

Automated coverage uses synthetic raw bytes and temporary DuckDB files. It
proves direct-family normalization, privacy substitution, all-family assembly,
tamper rejection, exact replay, transaction rollback semantics, read-back,
permission gates, and absence of implicit database creation or migration.

Implementation validation does not constitute operational acceptance. To close
P1-05, a separately approved private run must reuse the accepted exact Schwab
evidence, produce one assembly per account, validate mode 0700/0600 storage,
persist only to an isolated migration-0016 database, prove exact replay and
read-back, reconcile expected family counts and exclusions, and receive explicit
project-owner acceptance. No new provider call is required unless existing
evidence is later proven insufficient.

That bounded acceptance completed on 2026-09-06. Private run
`ONEJOURNAL-P1-05-SCHWAB-20260906-01` and owner acceptance
`ONEJOURNAL-P1-05-OWNER-ACCEPTANCE-20260906-01` are bound to the exact assembly
UID, fingerprint, audit, and manifest. Acceptance covers only the isolated
single-account import foundation. The assembly remains `review_required` for
its recorded fill mismatches and cash-currency omissions; no actual journal
migration, production route, provider capability, or broader financial
acceptance follows from P1-05 completion.
