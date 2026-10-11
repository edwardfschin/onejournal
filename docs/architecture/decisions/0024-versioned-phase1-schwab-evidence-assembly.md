# ADR-0024: Version the Phase 1 Schwab evidence assembly

- Status: Accepted
- Date: 2026-09-06
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, P1-08, WEB-W06, WEB-W07
- Related decisions: ADR-0003, ADR-0006, ADR-0007, ADR-0010, ADR-0016,
  ADR-0018, ADR-0020, ADR-0021, ADR-0022, ADR-0023
- Supersedes: None
- Superseded by: None

## Context

The prototype daily Schwab importer writes transaction-derived fills and
lifecycle events, then derives account, order, position, and transaction rows
from those fills. That loses valid source-family information and creates
placeholder semantics. Separately accepted position, quote/session, FIFO, and
broker-current P&L evidence must not be rewritten or silently promoted into a
new portfolio contract.

Phase 1 supports multiple owner-controlled Schwab accounts. It therefore needs
one repeatable import unit that is complete and exact for one opaque account,
can be replayed safely, and can later be combined only under explicit financial
and currency rules.

## Decision

OneJournal will use
`onejournal.schwab-phase1-evidence-assembly.v1` as the additive Phase 1 Schwab
import boundary. One assembly contains exactly one provider, connection,
opaque account, current position/quote market date, contiguous lifecycle
window range, and exactly these eight families:

1. account;
2. positions;
3. orders;
4. transactions;
5. fills;
6. cash;
7. quotes; and
8. sessions.

Each family preserves exact manifest and raw-response SHA-256 lineage, source
and normalized counts, exclusions with privacy-safe reasons, immutable
normalized records, and its own content fingerprint. The assembly fingerprint
covers the complete family set, scope, timing, reconciliation, and status and
is also its stable replay identity.

Direct Schwab evidence, not fill-derived reconstruction, supplies the account,
order, and transaction families. Account balances and type come only from the
account-position response and remain absent when Schwab omits them. Orders
retain their parent/child structure, leg evidence, stable logical order ID, and
every checksum-bound source-window observation; repeated order observations
are not discarded because Schwab order state can evolve across windows.
Transactions and cash rows likewise retain their logical IDs plus exact
source-window observation identities. Transactions retain their transfer-item
evidence. Cash rows preserve separately labelled Schwab
`netAmount`, security `cost`, and currency/fee item evidence without netting,
aggregation, relabelling, or P&L inference. Transaction fills remain the
authoritative fill family after exact order/transaction reconciliation.

The current complete position snapshot and quote capture must share the exact
provider, connection, and market date. The quote instrument set must be a
subset of the position instrument set; its exact covered and uncovered counts
are durable reconciliation fields. Every quote must bind to same-provider
session authority. A position without an independent quote remains present in
the assembly but unavailable to quote-dependent consumers. It does not make a
broker-current position value unavailable when a separately accepted contract
uses Schwab's exact current-position value instead. Lifecycle windows must
share the account, remain contiguous and non-overlapping, and end no later than
the current snapshot. One explicit native-currency consensus is required for
version 1; cross-currency conversion remains outside this decision.

Migration 0016 stores the complete assembly and its eight family payloads in
new private DuckDB tables. Persistence is atomic. An exact replay returns the
existing assembly; reuse of an identity with different stored content fails.
The writer requires a pre-existing migrated database and never creates or
migrates one implicitly. Read-back addresses the exact assembly UID and
revalidates all fingerprints and invariants; there is no latest-row fallback.

The operator defaults to validation. `--persist` is an explicit database-write
gate and accepts only pre-existing non-symlink mode-0600 artifact and database
files. It emits a privacy-safe audit containing identifiers, fingerprints,
counts, reconciliation, and status, but no symbol, raw payload, provider
account number, credential, or financial value.

## Fail-closed meaning

`ready` means only that this assembly is structurally complete, position and
quote coverage is explicitly reconciled, every included quote has exact
session authority, and the included order and transaction fills reconcile
without excluded fill rows. It does not mean:

- complete account history has been proven;
- FIFO, realized P&L, or broker-current valuation has been recalculated;
- an eligible subtotal is a portfolio total;
- multiple accounts may be consolidated;
- an authenticated API route is accepted;
- a production database has been migrated; or
- provider, credential, deployment, or order capability exists.

Any order-only fill, transaction-only fill, excluded fill row, or cash row
lacking explicit currency produces `review_required`. Downstream financial
consumers must reject that state or apply a separately accepted bounded route;
they must not repair it by guessing.

## Consequences

- Existing legacy fill-derived tables, quote captures, migrations 0013-0015,
  and historical PNL-03 evidence remain unchanged.
- An assembly can preserve a complete position snapshot plus a smaller accepted
  quote scope without fabricating marks or forcing a redundant provider call.
- A single owner can retain independent account assemblies without placing raw
  Schwab account numbers in durable normalized records or ordinary audit.
- A future PostgreSQL projection can consume the versioned assembly instead of
  copying prototype placeholder rows.
- Bounded operational acceptance was completed on 2026-09-06 by
  `ONEJOURNAL-P1-05-SCHWAB-20260906-01` and project-owner acceptance
  `ONEJOURNAL-P1-05-OWNER-ACCEPTANCE-20260906-01`. The exact private run proved
  first write, identical replay, read-back, checksums, and permissions while
  preserving its explicit `review_required` conditions.
- Live migration, production persistence, private evidence use, provider
  access, credential ownership, deployment, commit, and push remain separate
  approval boundaries.

## Rejected alternatives

- Continue using fill-derived placeholder families: rejected because source
  meaning and account/cash/order state are lost.
- Rewrite legacy normalized tables in place: rejected because it would mix a
  new contract with historical prototype behavior and complicate rollback.
- One assembly containing every Schwab account: rejected because an error in
  one account could contaminate another and replay identity would be unstable.
- Let the website join raw provider files at request time: rejected for
  privacy, latency, traceability, and financial-correctness reasons.
- Treat OneBot state or computed values as source evidence: rejected; OneBot is
  only the temporary credential-owning evidence bridge.

## Approved v3 addendum: 2026-10-11

The project owner approved a bounded offline correction, additive upgrade
preparation, disposable-copy rehearsal, commit and push. The contract now
offers a separate v3 path: at most two independent quote captures, exact UTC
snapshot cutoff, actual UTC query-window dates and independently preserved
provider quote/New York snapshot dates. Later financial activity is excluded
and counted before cross-window fill reconciliation. Session/freshness rules,
decimal-safe calculations, complete-position scope and old v1/v2 fingerprints
are unchanged. This fixes the observed 64-instrument and UTC/weekend date
incompatibilities without relabelling evidence.

Migration 0027 adds a single immutable private canonical-artifact store instead
of rebuilding accepted tables or duplicating ten family tables. It preserves
all family payloads and validation, with exact scope/checksum read-back. Pure
calculation consumers support v3, but legacy history activation fails closed
before database access; migration 0021's v2 foreign keys/date constraints have
not been bypassed. Compatible history/report refresh integration remains a
separate unfinished implementation step, not an accepted operational capability.

The approval excludes broker access, live database writes, deployment and
runtime changes. No fresh quote/session evidence or private v3 financial
release exists yet. Product strategy, financial methodology, accepted reporting
scope and Phase 1 maturity remain unchanged. Before live use, rollback is a
focused source revert; existing immutable evidence is never deleted.

### Approved history compatibility follow-up: 2026-10-11

The next approved local implementation adds migration 0028 and history-revision
contract v2 for exact-cutoff assembly v3. Separate physical revision/child tables
retain the old schema and accepted rows; unified current views retain existing
public column shapes. A cross-generation activation ledger supports explicit
rollback, with transactional account/target/predecessor checks. Migration does
not activate a revision. The writer verifies all reconstructed rows before commit
and on replay; replacing snapshot history with legacy history requires rollback.

The realized-result/calculation version changes only on snapshot authorities:
the exact UTC cutoff is fingerprint-bound and checked against UTC query end and
New York snapshot date. Boundary instants are included and later activity excluded.
Date coverage describes dates overlapping the bounded source window, not proof of
complete account history or full boundary-day sessions. Legacy calculation and
assembly fingerprints remain unchanged.

Quote-capture/artifact v2 can preserve four explicitly approved unavailable
responses without prices or inferred timestamps. Assembly v3 records those quote
exclusions while keeping positions and raw lineage. New unsupported provider
states still stop normalization; six `Halted` states in the fresh capture are not
silently admitted. A disposable live-journal copy reached 0028 with all 81 old
relation hashes/counts, accepted report and legacy realized fingerprint unchanged.
This is schema/source validation, not fresh financial reconciliation or operational
acceptance. No live write or runtime activation was performed.

### Approved halted-price extension and private rehearsal: 2026-10-11

The owner subsequently approved withholding the six exact provider-reported
halted instruments. The credential-free multi-batch converter accepts at most
six distinct explicitly mapped halted identities, disjoint from the at-most-four
undated identities. Only an actual `Halted` state enters this branch; an unknown
state is not inferred to be halted. Without this explicit scope, the strict
adapter still rejects the response.

Unavailable records carry `unavailable_provider_security_halted` or
`unavailable_provider_quote_timestamp`, raw checksum and exact mapped identity,
but no price or replacement quote timestamp. Capture validation, artifact
read-back, persistence/replay and assembly exclusions preserve the distinct
reason. Positions are retained; quote-dependent totals remain unavailable.
The operator's repeatable `--halted-quote-symbol` option is limited to the v2
multi-batch profile. `--require-valuation-allowed` still rejects any unavailable
instrument before materialization. No legacy fingerprint or public API changes.

Actual private saved-data rehearsal now verifies 54 available and ten unavailable
quotes, exact-cutoff history activation/read-back/replay, bounded realized
calculation, cross-version rollback, broker-current as-of-snapshot valuation and
exact prospective report storage. It preserves the accepted release and every
pre-existing base-table row. This establishes calculation and copy compatibility,
not owner acceptance of the new fingerprints, a live report release or current
quote completeness. The accepted live database and runtime are unchanged.
The value-free evidence and remaining release boundary are recorded in
`docs/mac_data_refresh_capture_plan.md`. Strategic maturity remains unchanged.
