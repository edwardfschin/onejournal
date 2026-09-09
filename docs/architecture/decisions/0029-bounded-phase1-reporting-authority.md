# ADR-0029: Define a bounded Phase 1 reporting authority

- Status: Accepted
- Date: 2026-09-07
- Accepted date: 2026-09-07
- Decision owners: OneJournal project owner
- Related roadmap items: P1-08, PNL-06, PNL-07, PNL-08, WEB-W08
- Related contracts: ADR-0003, ADR-0004, ADR-0007, ADR-0018, ADR-0023,
  ADR-0024, ADR-0025, ADR-0028,
  `docs/phase1_reporting_release_contract.md`
- Supersedes: None
- Superseded by: None

## Context

WEB-W07 exposes one exact owner-accepted broker-current valuation through the
private loopback application. The operational journal is at migration 0023 and
contains one broker-current run with complete current-position cost-basis,
market-value, and unrealized-P&L coverage for its declared snapshot.

A read-only 2026-09-07 audit also established that the operational journal
contains zero `pnl_calculation_runs`, zero `pnl_closed_lot_allocations`, zero
`pnl_lifecycle_allocations`, and zero `pnl_group_results`. It therefore has no
operational realized-P&L authority from which WEB-W08 can truthfully build a
date-filtered P&L history, realized totals, or a matching export.

The five PNL-01 trust proofs remain valid for their exact accepted lifecycle
cases. Their aggregate acceptance explicitly excludes complete account
history, portfolio-wide correctness, and database or migration authority.
They are validation evidence, not an operational reporting dataset, and their
case-specific results must not be silently copied into a portfolio report.

The current journal history is more useful but still bounded. It contains
complete and incomplete lifecycle scopes, and WEB-W06 intentionally gives none
of them P&L authority. A report implementation must therefore create a new,
separately accepted financial result rather than calculating inside an API
request or treating cash movement as P&L.

The current API also withholds source account identifiers, while the
operational `normalized_accounts` table contains no account rows from which a
safe display name can be obtained. Account views need an explicit private alias
binding rather than a guessed label or an exposed broker identifier.

## Decision

Adopt `onejournal.phase1-report-release.v1` as the only authority for the
bounded Phase 1 reporting slice.

The release will bind, by exact identity and fingerprint:

1. one or more owner-accepted broker-current valuation runs;
2. one newly calculated and separately owner-accepted realized-P&L result built
   only from eligible operational lifecycle evidence;
3. the exact active history revision used by that calculation;
4. a private, stable, owner-chosen account alias for every included source
   account; and
5. coverage dates, processed/available/unavailable counts, reason counts,
   calculation versions, currency units, and acceptance lineage.

The realized result will admit only lifecycle allocations whose opening and
closing evidence is complete for the calculation scope, whose executions and
terminal events reconcile, and whose account, instrument, direction, quantity,
multiplier, currency, costs, and timestamps satisfy accepted P&L contracts.
Every excluded lifecycle remains counted with a privacy-safe reason. An
unsupported or incomplete lifecycle cannot contribute a value or become zero.

The request path will read accepted persisted results only. It will not call a
provider, read raw evidence, rebuild lifecycles, calculate P&L, select a newer
run, or infer an account label. Process-start authorization must match the exact
report release identity and fingerprint before any financial value is returned.

Account and symbol breakdowns will be deterministic views of the accepted
records. The Phase 1 symbol key is the existing owner-facing position symbol:
the equity symbol for equities and the explicit underlying symbol for options.
Exact instrument identity remains attached to every source record so the
grouping cannot merge or reinterpret contracts.

Date filters apply inclusively to the accepted New York market date derived
from each close or lifecycle effective UTC instant. A zero-activity result is
valid only when the accepted release proves complete coverage for the entire
requested scope and date range. A request outside the accepted coverage range
is unavailable or incomplete, never zero.

CSV export will be generated from the same validated selection object used by
the displayed view. The API response and export will carry the same selection
fingerprint, counts, reason counts, currency, date range, and report release
identity. The export will omit source account IDs, provider order/transaction/
fill IDs, raw paths, journal prose, credentials, and private evidence.

Current-position account and symbol totals may be valid when they reconcile to
the accepted WEB-W07 current-valuation total. Realized-P&L subtotals may be valid
for the explicitly admitted lifecycle set. A consolidated total P&L remains
unavailable unless realized and unrealized components are both valid for the
same account, currency, instrument, and as-of scope. The system will not add a
bounded realized subtotal to a wider current-portfolio unrealized total.

## Boundaries

This decision includes only the Phase 1 account/symbol current breakdown,
date-filtered realized-P&L history, matching CSV exports, and complete ADR-0007
quality states required by WEB-W08.

It does not approve or complete:

- full account-history or portfolio-wide realized-P&L correctness;
- historical portfolio snapshots, returns, drawdown, exposure, tax reporting,
  or advanced strategy analytics;
- arbitrary account labels derived from broker data;
- a database migration, private calculation, persistence, API activation,
  browser acceptance, hosting, deployment, commit, push, or provider access;
- authenticated or public access; or
- any broker order or trading capability.

PNL-06, PNL-07, and PNL-08 remain blocked as broader roadmap items even if
their exact bounded Phase 1 slices later complete under WEB-W08.

## Alternatives considered

### Build a new bounded operational realized-P&L release

This produces useful history from the journal the owner already browses while
preserving a strict eligibility and omission boundary. It requires a new
calculation/reconciliation package, additive persistence, explicit owner
acceptance, and report-release authorization. This is the recommended option.

### Publish only the five historical PNL-01 proof cases

This would reuse already accepted case evidence, but those proofs were designed
to validate distinct financial behaviors rather than form a coherent account
history. Their aggregate acceptance grants no operational database authority,
and shared account/report identity has not been established. This option is too
narrow for WEB-W08 and risks presenting test-like scopes as portfolio history.

### Wait for complete account history

This would make wider realized totals possible but would couple the finite
Phase 1 release to additional evidence acquisition and lifecycle closure. ADR-
0018 permits a smaller explicitly supported scope with visible omissions, so
waiting is unnecessary as long as incomplete scopes never enter accepted
values or totals.

## Consequences

### Positive

- Every displayed and exported value has one explicit financial authority.
- The owner gets useful current breakdowns and bounded realized history without
  hiding incomplete lifecycles.
- API, UI, and CSV use the same deterministic selection and reconciliation
  rules.
- Account privacy is preserved through explicit aliases rather than source IDs.
- Later history extensions can append a new release without rewriting an older
  accepted report.

### Negative and trade-offs

- Initial realized history will be explicitly partial and cannot support a
  portfolio-wide total P&L.
- A new calculation acceptance and additive persistence path are required
  before WEB-W08 can show real historical values.
- The owner must choose stable account aliases in private evidence.
- Each expanded history revision requires recalculation, reconciliation, and a
  new accepted report release.

## Compatibility and migration

The decision is additive. The WEB-W07 response contract and W07 current route
remain unchanged. A future migration may add immutable report-release,
accepted-realized-allocation, account-alias binding, export-selection, and
value-free audit tables; it must not rewrite the existing P&L, history-revision,
or broker-current valuation tables.

The producer chain is:

```text
accepted evidence assembly and active history revision
-> deterministic eligible lifecycle selection
-> versioned realized-P&L calculation and reconciliation
-> explicit owner acceptance
-> immutable Phase 1 report release
-> loopback report API
-> local Portfolio/Reports views and matching CSV exports
```

The broker-current branch continues to come from the exact accepted WEB-W07
run. A report release references it; it does not duplicate or reinterpret it.

## Security, privacy, and financial impact

The report release and account-alias binding are owner-private evidence and must
use existing private-root, mode-`0700` directory, mode-`0600` file, no-symlink,
checksum, and canonical-path controls. Account aliases must be explicit and
must not contain broker account numbers or hashes.

Browser requests can select only an already admitted alias, symbol, and date
range. They cannot provide a database path, raw path, account identifier, SQL,
run identity, authorization file, or calculation input. Audits are value-free
and never record positions, P&L, journal prose, account identifiers, or CSV
content.

Financial values remain Decimal throughout persistence and API serialization.
Native currencies are never combined without an accepted FX contract. Missing
or invalid evidence remains unavailable; it is never defaulted to USD or zero.

## Validation and approval gates

Implementation must remain split into independently approved gates:

1. **Gate 1 — contract:** owner approval of this ADR and
   `docs/phase1_reporting_release_contract.md`.
2. **Gate 2 — local implementation:** deterministic eligibility, calculation,
   additive migration, repository, API, CSV, UI, and synthetic/temporary-DB
   tests only.
3. **Gate 3 — private realized-result acceptance:** checksum-bound calculation
   and reconciliation against the intended private history revision, followed
   by explicit owner acceptance of that exact result.
4. **Gate 4 — live persistence:** verified backup, disposable-copy rehearsal,
   separately approved migration, exact accepted-result persistence, read-back,
   integrity checks, and rollback evidence.
5. **Gate 5 — local API and browser verification:** loopback-only activation,
   API/view/CSV parity, quality and negative-state checks, responsive and
   accessibility checks, and at most the explicitly approved value-free audit
   rows.
6. **Gate 6 — owner acceptance:** explicit acceptance of the demonstrated
   private local-only WEB-W08 scope.
7. **Gate 7 — Git:** commit and push remain separate explicit approvals.

No later gate is implied by approval of an earlier gate.

Gate 1 was explicitly approved by the OneJournal project owner on 2026-09-07
for the bounded WEB-W08 reporting design and contract only. That approval did
not authorize implementation or private database work.

The original Gate 2 slice was merged on 2026-09-08. A subsequent private
calculation attempt correctly exposed the missing active-history calculation
operator and was not accepted. Migration 0024 was separately rehearsed and
applied, with its new tables left empty. The Gate 2 precision correction adds
the missing read-only, deterministic calculation and omission boundary.

The corrected Gate 3 calculation was run read-only on 2026-09-08. Exact replay
produced fingerprint
`bd05ac8f87e58b9fdc57792cd19f763ee40a136dcd692e8e0399d19227566063`
over one active revision covering 2026-03-06 through 2026-09-04. It admitted
230 realized allocations and withheld 57 scopes: 28 for missing opening
history, 13 for incomplete position reconciliation, and 16 for lifecycle
review. Result validation, reporting-item value-sum parity, omission/reason
parity, date coverage, and journal integrity passed. Exact replay returned the
same fingerprint, and the database SHA-256 remained
`16a6088aacefc2bbf1d0fce707502945e8d0eab754c7b531ab8a72ebe50f4c6e`.
The result is explicitly `incomplete` and is not a complete portfolio realized
P&L. On 2026-09-09, the project owner explicitly accepted this exact bounded
result under acceptance UID
`ONEJOURNAL-WEB-W08-GATE3-OWNER-ACCEPTANCE-20260909-01`. The acceptance is
limited to fingerprint
`bd05ac8f87e58b9fdc57792cd19f763ee40a136dcd692e8e0399d19227566063`,
230 admitted allocations, 57 withheld scopes, and the declared coverage. It
does not authorize persistence, a complete realized-P&L claim, API activation,
browser acceptance, commit, or push. Gate 3 is complete for that exact scope.

Migration 0025 corrects the still-empty release schema by preserving separate
owner-acceptance identities and UTC instants for the current-valuation and
realized-result fingerprints. Its 2026-09-09 disposable-copy rehearsal reached
0025 with all 81 compared data-table row counts unchanged and journal integrity
clean; the live journal remained at 0024 with its checksum unchanged. This does
not by itself authorize the live migration or report-release persistence. The
owner then separately approved a fresh checksum-matched backup and live 0025
migration only. The live journal reached 0025 on 2026-09-09 with all 81 compared
data-table row counts unchanged, integrity clean, and every reporting table
still empty. The verified 0024 backup remains the rollback artifact. No report
release or API audit row was written.

The correction is locally validated by 546 passing tests plus 267 passing
subtests, focused migration and route checks, frontend lint, and the production
frontend build. These checks use synthetic or temporary data and do not
constitute Gate 3 private-result acceptance.

## Rollback or supersession

Before Gate 4, rollback is a focused code/document reversion and disposal of
temporary databases. After an additive operational migration, disabling the
process-start report authorization immediately withholds all report values
without deleting accepted state. Persisted releases and audit rows remain
append-only. A failed migration restores the verified pre-migration backup
under the database recovery procedure. A later reporting policy must supersede
this ADR and preserve historical release fingerprints and acceptance records.
