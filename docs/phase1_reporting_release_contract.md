# Phase 1 reporting release contract

- Contract: `onejournal.phase1-report-release.v1`
- Status: Accepted under ADR-0029 on 2026-09-07
- Scope: P1-08 and WEB-W08 bounded Phase 1 reporting only

## Purpose

This contract defines the smallest report authority that may feed the private
Phase 1 account/symbol breakdown, date-filtered realized-P&L history, and CSV
exports. It does not itself authorize a calculation, database change, value
release, API activation, hosting, or deployment.

## Verified starting state

At contract approval, the private operational journal was at migration 0023.
It contained one accepted broker-current valuation run used by WEB-W07 and no
operational realized-P&L calculation or allocation rows. The current API omits
source account identity, and the operational normalized-account table supplies
no account label.

Accordingly, WEB-W08 must fail closed until a release binds both a realized
authority and a private account alias. Current-position breakdowns may continue
to use the exact accepted WEB-W07 run, but they must not imply that realized or
total P&L exists.

Migration 0024 was later applied under its separate live-migration approval.
The reporting tables remain empty until an exact calculated result and owner
acceptance pass the later persistence gate.

Before Gate 4 persistence, migration 0025 must correct the empty release table
so the current-valuation acceptance and realized-result acceptance are stored
as two separate identity-and-UTC-time pairs. This is not a reinterpretation or
backfill: 0025 fails closed if any release row already exists. Preparing or
rehearsing 0025 does not authorize a live database write or a report release.
The 2026-09-09 disposable-copy rehearsal succeeded: the copy advanced to 0025,
all 81 compared data-table row counts remained identical, journal integrity
passed, and the live journal remained at 0024 with its checksum unchanged.
The owner later approved the fresh backup and live 0025 migration only. The
live journal reached 0025 on 2026-09-09 with the same 81 data-table row counts,
clean integrity, and zero rows in all five reporting tables. The backup remains
at 0024 for rollback. This live schema migration still does not authorize or
constitute report-release persistence.

The first exact release rehearsal then proved that the realized-item
`DECIMAL(38,13)` column would change 16 values in the already accepted result.
Read-back fingerprint validation stopped the write, the private package was not
created, and the live journal remained unchanged. Migration 0026 therefore
widens only that still-empty item column to `DECIMAL(38,27)`. A fresh disposable
copy reached 0026, preserved 67 non-reporting base-table row counts, persisted
the release twice idempotently, and read back all 230 admitted items and 57
withheld scopes exactly. The live journal remains at 0025 with every reporting
table empty; live migration 0026 and report persistence remain unapproved.

Gate 3 owner acceptance was granted on 2026-09-09 for bounded realized-result
fingerprint
`bd05ac8f87e58b9fdc57792cd19f763ee40a136dcd692e8e0399d19227566063`,
with 230 admitted allocations and 57 withheld scopes. Acceptance UID
`ONEJOURNAL-WEB-W08-GATE3-OWNER-ACCEPTANCE-20260909-01` records that exact
scope. No report-release persistence is authorized by this acceptance.

The owner chose the private alias `Primary` and explicitly approved preparation
of the combined release on 2026-09-09. The prepared release is
`ONEJOURNAL-WEB-W08-REPORT-RELEASE-20260909-01`, fingerprint
`506a4b49810e4da77f3880818a83425c835eb9cd25d08b1503dd95ed9d6ddb2c`.
Its value-free private package binds the exact current and realized authorities,
separate acceptance lineage, 287 processed scopes, the omission reasons, and
the successful disposable-copy rehearsal. The authorization file is prepared
but not active.

## Impact map

| Area | Contracted impact |
|---|---|
| Authoritative current source | Exact owner-accepted WEB-W07 broker-current valuation run |
| Authoritative history source | New owner-accepted realized-P&L result over one exact active history revision |
| Upstream producer | Existing accepted evidence assembly, history materialization, lifecycle reconciliation, and versioned P&L calculation |
| Changed component | Additive immutable report-release persistence and read-only report service |
| Downstream consumers | Loopback report API, local Portfolio/Reports views, and CSV serializer |
| Persisted state | Future additive report release, admitted realized items, alias binding, and value-free audit rows |
| User-facing surfaces | Account breakdown, symbol breakdown, realized history, quality states, and downloads |
| Validation | Exact reconciliation, API/CSV parity, negative states, privacy, accessibility, responsiveness, and full regression |
| Rollback | Withhold process-start authorization; preserve append-only releases; restore verified backup only for migration failure |

## Release identity and authority

A report release is immutable and contains:

- `contract_version`;
- `report_release_uid` and `report_release_fingerprint`;
- `current_valuation_run_uid` and its accepted result fingerprint;
- `realized_calculation_run_uid` and its accepted result fingerprint;
- `history_revision_uid` and the exact active-revision evidence used;
- explicit owner-acceptance identities and UTC instants for both financial
  branches and the combined report release;
- supported account aliases, currencies, instruments, and inclusive New York
  market-date coverage;
- calculation and grouping versions;
- processed, available, unavailable, and reconciliation-pending counts;
- a count for every omission reason; and
- one deterministic fingerprint over all admitted records and metadata.

The release fingerprint changes when any included value, identity, date,
quality state, count, reason, alias binding, or authority fingerprint changes.

## Private account aliases

Every source account in a release maps to one stable, owner-chosen alias.

- The mapping is private process-start or persistence input, never inferred
  from a broker account label, number, digest, or row order.
- Aliases are non-empty, unique within the release, and contain no account
  number or account hash.
- API and CSV return the alias only. Source account IDs remain server-side.
- A missing, duplicate, conflicting, or unsafe alias blocks the release.

## Realized-P&L eligibility

Each admitted history item must be backed by an accepted allocation with:

- exact source account and instrument identity;
- complete opening and closing evidence for the admitted quantity;
- confirmed fills or an approved supported lifecycle allocation;
- reconciled execution or lifecycle evidence;
- explicit direction, quantity, multiplier, currency, fees, and commissions;
- a canonical UTC close/effective instant and derived New York market date;
- calculation version and input/result fingerprints; and
- an owner acceptance matching the exact result fingerprint.

`review_required`, opening-history-missing, unsupported lifecycle,
unreconciled, currency-missing, multiplier-missing, identity-conflicting, or
otherwise incomplete scopes are unavailable and contribute no financial value.
They remain represented in count and reason metadata.

The bounded calculation operator reads only the exact active history revision
set. It fails if that revision is stale against normalized fills, if any active
execution economics are unreconciled, or if an unmatched close appears in a
scope marked resolved. Allocations whose opening or closing evidence touches an
unresolved episode are withheld. Each unresolved episode produces one
value-free omission, while every admitted allocation retains its exact opening,
closing or lifecycle-event lineage inside the fingerprinted calculation result.

## Read models

### Current account breakdown

One row per admitted account alias and currency, derived only from the exact
accepted current valuation positions. Cost basis, market value, and unrealized
P&L are independently available. A row reconciles exactly to its contributing
positions, and all valid rows reconcile to the same-currency WEB-W07 total.

### Current symbol breakdown

One row per account alias, owner-facing symbol, and currency. The symbol is:

- the explicit equity symbol for an equity; or
- the explicit underlying symbol for an option.

Exact instrument keys remain in the contributing records. Grouping never
changes instrument identity, multiplier, lot method, or value. Missing symbols
make the affected item unavailable.

### Date-filtered realized-P&L history

Filters are inclusive `from` and `to` New York market dates plus optional
admitted account alias and owner-facing symbol. Invalid dates, `from > to`,
unknown aliases, unknown symbols, and ranges outside accepted coverage fail
with an actionable privacy-safe response.

Every history item carries an opaque report item ID, account alias, owner-facing
symbol, asset class, close market date, currency, realized P&L, calculation
version, and item quality. It omits source fill/event/account identities and
private paths.

An empty result is `valid` with value zero only when the release proves full
coverage for the entire requested scope and range. Otherwise the result is
`incomplete` or `unavailable`, with no financial zero.

### Total P&L

Total P&L is present only when realized and unrealized components are both
valid for the same account, symbol/instrument scope, currency, and as-of
boundary. A bounded realized subtotal must not be added to a wider current
unrealized total. Until scope equality is proven, total P&L is unavailable with
reason `realized_and_unrealized_scope_mismatch`.

## Quality contract

Every response-level metric, group row, and history selection uses exactly one
ADR-0007 state:

`valid`, `stale`, `incomplete`, `reconciliation_pending`, `unavailable`, or
`failed`.

Every collection publishes:

- `processed_count`;
- `available_count`;
- `unavailable_count`;
- `reconciliation_pending_count`; and
- `reason_counts` with one reason for every unavailable or pending item.

The most restrictive contributing state propagates to an aggregate. A partial
subtotal is explicitly labelled and cannot become a consolidated total.
Missing values serialize as null, never zero. A mathematical zero is emitted
only from valid admitted records.

## API boundary

The exact paths remain an implementation detail until Gate 2, but the API must
provide separate read resources for:

- current account breakdown;
- current symbol breakdown;
- date-filtered realized history;
- current-position CSV export; and
- filtered realized-history CSV export.

All resources require one exact process-start report-release authorization.
Without it they return an unavailable response without values. Browser input
cannot select a database, run, revision, authorization, source account, raw
path, calculation method, or provider.

The process-start file uses contract
`onejournal.phase1-report-release-authorization.v1`, requires owner-private
`0700`/`0600` directory and file permissions, and binds the exact report release
UID, fingerprint, and owner-acceptance UID. It cannot request calculation or
persistence and is rejected if it is a symlink, malformed, over-specified, or
does not match the persisted release.

## CSV parity

The CSV serializer consumes the same validated in-memory selection as the JSON
view. It does not issue a second financial query or recalculate values.

Current-position export columns are:

```text
report_release_uid,selection_fingerprint,asof,account_alias,symbol,instrument_key,asset_class,currency,quantity,cost_basis,cost_basis_status,market_value,market_value_status,unrealized_pnl,unrealized_pnl_status,position_status,reason_codes
```

Realized-history export columns are:

```text
report_release_uid,selection_fingerprint,from_market_date,to_market_date,item_uid,close_market_date,account_alias,symbol,asset_class,currency,realized_pnl,item_status,reason_codes,calculation_version
```

Rows use stable deterministic ordering. Decimal text, dates, nulls, reason
ordering, and CSV escaping are contract tested. The export response includes
the same selection fingerprint and counts as the corresponding JSON response.

## Audit and privacy

Read audits record only operation ID, action, report release UID, selection
fingerprint, filter-presence flags, counts, outcome, and UTC time. They do not
record symbols, aliases, dates, values, positions, account IDs, journal prose,
CSV bytes, paths, or credentials.

No report route calls a provider or broker order endpoint. Automatic trading
remains disabled and outside this contract.

## Required validation

Gate 2 must prove with synthetic and temporary-DuckDB data:

- exact account and symbol reconciliation to the current valuation source;
- exact realized allocation reconciliation by account, symbol, date, and
  currency;
- API/CSV record, value, count, reason, order, and fingerprint parity;
- full/partial/unavailable/stale/pending/failed and valid-zero states;
- date boundaries, unknown filters, range coverage, and no false zero;
- no cross-currency total without an accepted FX contract;
- no source account, provider identity, raw path, private prose, or credential
  in API, CSV, audit, log, exception, fixture, or generated asset;
- exact authorization mismatch and stopped-API negative behavior;
- idempotent persistence and exact read-back;
- desktop, tablet, mobile, keyboard, focus, table/overflow, and download
  behavior; and
- focused tests, full clean CI, frontend lint/build, database integrity, and
  automatic-trading-disabled checks.

Private calculation, operational migration/persistence, local accepted reads,
browser verification, owner acceptance, commit, and push remain the later
separate gates defined by ADR-0029.
