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
