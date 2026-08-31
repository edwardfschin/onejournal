# OneJournal

OneJournal is a broker-independent trading journal, portfolio, and performance
platform under active development.

The current application is an internal Streamlit prototype used to validate
data contracts, journal workflows, and safety boundaries. It is not the final
production website. The intended product is a polished, responsive, secure,
and trustworthy website for trading review, portfolio monitoring, realized and
unrealized P&L, strategy analytics, risk monitoring, and—only after separate
safety gates—controlled automated trading.

## Current status

Implemented and validated today:

- Broker-independent models for accounts, orders, fills, positions, and
  transactions
- Manual CSV normalized-fill ingestion
- Schwab orders and transactions JSON normalization
- Guarded Schwab reconciliation and optional DuckDB import
- Import audit records and idempotency checks
- DuckDB journal tables for normalized fills, trade-episode previews, legs,
  and manual reviews
- Deterministic trade-lifecycle matching and replay-safe correction support
- FIFO lot calculations for supported confirmed-fill scopes, with fail-closed
  handling for unmatched closes and unsupported lifecycle cases
- As-of-filtered dashboard positions, portfolio snapshots, performance metrics,
  breakdowns, and per-metric quality states
- Generated dashboard payloads and a Streamlit review interface
- Reproducible locked dependencies, automated tests, and clean-checkout CI
  tooling

Not implemented or not yet trustworthy:

- Broker-reconciled, lifecycle-event-allocated P&L across the complete
  portfolio scope (including the remaining complex lifecycle cases)
- Continuous provider-backed market-data acquisition and PNL-03-approved
  valuation marks for real portfolio use
- Daily, monthly, and custom-period reports and exports, plus an approved
  return-denominator and equity-curve policy
- Production authentication, API/frontend implementation, hosted runtime, or
  deployment
- IBKR ingestion beyond its reserved adapter/configuration boundary
- Paper or live automated trading

The current dashboard's gross cashflow is not profit or loss. No displayed
prototype value should be interpreted as tax, accounting, or investment advice.

## Initial production scope

The approved first production scope is:

- one authenticated user with multiple owned brokerage accounts
- Schwab first, followed by IBKR through the same normalized contracts
- US-listed stocks and listed equity options
- read-only journaling, portfolio, P&L, analytics, and risk workflows
- no broker order execution

See [ADR-0002](docs/architecture/decisions/0002-initial-product-scope.md)
for inclusions, exclusions, sequencing, and unresolved instrument boundaries.

[ADR-0018](docs/architecture/decisions/0018-phase-1-private-owner-release.md)
now defines the finite **Phase 1 — Private Owner Release**. It requires a
secure private single-owner website with a repeatable read-only Schwab evidence
route, supported trade/journal workflows, broker-reconciled current positions,
accepted realized and unrealized P&L, bounded account/symbol reporting and
export, explicit quality states, backup/restoration, and owner acceptance.

IBKR/Moomoo, multi-user or public features, continuous OneJournal-owned Schwab
connectivity, attachments, advanced journal routines, advanced analytics, and
paper/live/automated trading are post-Phase 1 and do not block that release.
The authoritative 12-item completion tracker is in the
[product roadmap](docs/onejournal_product_roadmap.md#phase-1---private-owner-release).

## Safety boundary

OneJournal is read-only with respect to brokerage accounts:

- No order placement
- No order cancellation, replacement, or modification
- No auto-trading
- No execution-plane code connected to the journal or Streamlit paths

The Streamlit prototype can write manual review fields to the local DuckDB
journal and regenerate dashboard output. A separate operator script can fetch
Schwab history through read-only endpoints when explicitly configured with
private credentials. Neither capability authorizes broker write operations.

The active safety settings are declared in `config/app.yaml` and
`config/journal.yaml`. Private environment files and broker tokens stay outside
the repository.

## Architecture and data flow

```text
raw broker or manual evidence
-> broker-specific adapter
-> broker-independent normalized records
-> validation and reconciliation
-> DuckDB journal
-> lifecycle and financial calculations
-> application/API service
-> dashboard payload or production website
```

Broker-specific payloads must not be parsed by Streamlit or written directly to
trade episodes, reports, or dashboard output.

Current source boundaries:

| Source | Current capability |
|---|---|
| Manual CSV | Normalized-fill parsing, validation, import, and tests |
| Schwab | Credential-free orders/transactions JSON adapters, reconciliation, and guarded import of externally acquired raw evidence |
| IBKR | Reserved raw directory, configuration, and package boundary; adapter not implemented |
| Market data | Provider-neutral Schwab quote/session/freshness ingestion is accepted only for the bounded owner-operated local bridge scope; continuous/live connections remain disabled, with IBKR next and Moomoo later |

All normalized activity preserves `source_broker` and `source_account_id` so
future journal and portfolio logic can distinguish brokers and accounts without
embedding broker formats in the domain or UI.

For the bounded PNL-02 bridge mode accepted on 2026-08-31, OneBot/VPS remains
the temporary single owner of the available Schwab application and refreshable
token. The current OneJournal runtime has no active Schwab credential or
provider-call operator and consumes only separately approved private evidence
bundles.

ADR-0016 accepts that credential-free bridge as the bounded local PNL-02
completion route. T16 proved exact external acquisition, OneJournal-owned
conversion and session/freshness assessment, append-only private
materialization, isolated DuckDB persistence, exact read-back, identical
replay, and fail-closed cases; the project owner accepted that stated scope on
2026-08-31. This does not approve continuous acquisition, a public website data
service, production database migration, PNL-03 valuation marks, or
OneBot-derived state as OneJournal authority.

The credential-free `onejournal.external-provider-acquisition.v1` intake and
conversion boundary is implemented, offline-tested, and validated against the
bounded T16 Schwab evidence. It validates canonical external lineage and exact
quote/market-hours bytes, then uses OneJournal's own adapters. Its guarded
operator defaults to validation-only; private materialization and the separate
durable-ingestion database write remain explicit actions. See
[`docs/external_provider_acquisition_contract.md`](docs/external_provider_acquisition_contract.md).

The target architecture removes that OneBot dependency: OneJournal becomes the
only project that owns approved provider connections and calls Schwab, IBKR,
Moomoo, or later providers through isolated provider-specific connectors. All
connectors produce the same broker-independent evidence and normalized
contracts, so journal, P&L, portfolio, and UI code remain provider-independent.

## ODFS repository layout

| Path | Responsibility |
|---|---|
| `config/` | Safe non-secret configuration, schemas, and policies |
| `data/raw/` | Immutable private source evidence; never committed |
| `data/normalized/` | Broker-independent transport and validation artifacts |
| `data/journal/` | DuckDB journal source of truth and review state |
| `data/audit/` | Run history, reconciliation, validation, and traceability |
| `output/` | Generated dashboard payloads, reports, charts, and exports |
| `src/onejournal/` | Reusable domain, adapter, service, and application code |
| `scripts/` | Operator commands and controlled maintenance |
| `docs/` | Contracts, architecture, roadmap, and runbooks |
| `tests/` | Unit, integration, contract, and regression tests |

Raw broker evidence, runtime databases, generated output, credentials, and
tokens are intentionally excluded from Git.

## Development setup

OneJournal supports Python 3.11 through 3.13. The currently validated local
environment uses Python 3.13.9.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
```

The exact setup contract and dependency-update process are documented in
[Development Setup](docs/development_setup.md).

## Validation

Run clean-checkout validation without private broker data or a runtime journal:

```bash
./bin/onejournal_ci.sh
```

Run the full local operational baseline when private prerequisites and the
runtime journal are present:

```bash
./bin/onejournal_check.sh
```

The full baseline may regenerate local validation and dashboard artifacts. A
passing clean CI check does not prove the private runtime database or broker
evidence is healthy; the two checks have deliberately different scopes.

See [Continuous Integration](docs/continuous_integration.md) and
[Automated Tests](tests/README.md).

## Running the internal prototype

Follow the [Operator Quickstart](docs/operator_quickstart.md) to validate the
local journal and build the DuckDB-backed dashboard payload. Then launch:

```bash
streamlit run src/onejournal/apps/streamlit_app.py
```

DB payload mode is the only writable review mode. CSV and custom payload modes
are read-only. Saving a review updates DuckDB `manual_reviews` and regenerates
the DB dashboard payload; it never contacts a broker order endpoint.

For guarded imports, use the
[Import Runbook](docs/operator_import_runbook.md). Do not experiment on the
runtime journal database; database changes must first be validated on a
temporary copy.

## Project direction

The dependency-ordered source of truth is the
[OneJournal Product Roadmap](docs/onejournal_product_roadmap.md).

Significant technical and policy decisions follow the
[Architecture Decision process](docs/architecture/README.md). Durable DuckDB
changes follow the [Database Migration Convention](docs/database_migrations.md).

Financial contracts—currency, time, identifiers, lifecycle semantics, cost
basis, realized P&L, unrealized P&L, fees, and reconciliation—must be approved
before those values are implemented or presented as trustworthy.

ADR-0017 now selects the production application foundation: React and
TypeScript built with Vite, Tailwind CSS, shadcn/ui with Base UI, Apache
ECharts, and a FastAPI authority boundary. DuckDB remains the current local
journal and analytical store; PostgreSQL is the migration-gated target for a
future hosted multi-process runtime. Long-running work remains outside
interactive requests, and the topology must stay self-hostable and
vendor-neutral. See the
[Production Web Delivery Contract](docs/production_web_delivery_contract.md)
for the visible WBS, design direction, data modes, security gates, and
acceptance boundaries.

The selected foundation is policy only: no frontend workspace, API,
authentication, hosted database, hosting target, deployment, or private web
runtime exists yet. Streamlit remains an internal workflow-validation surface
until the production website reaches verified parity.

## Working standards

Repository-wide operating rules are defined in [AGENTS.md](AGENTS.md).
Important changes require complete relevant dependency understanding, a concise
impact map, the smallest safe implementation, validation proportional to risk,
and a known rollback path. Generated artifacts are repaired through their
producers, and unrelated local work must be preserved.
