# OneJournal web fixture API v1

## Scope

`GET /api/v1/preview` is the first versioned FastAPI/frontend boundary for
WEB-W05. It returns deterministic, committed demonstration data only.

It never reads DuckDB, broker raw evidence, generated dashboard output,
credentials, configuration secrets, or a provider response. It does not write
data or initiate work.

## Contract rules

- The response declares `contract_version: onejournal.web-fixture.v1` and
  `mode: demo`.
- Financial quantities are decimal strings; the browser may format them but
  must not calculate authority from them.
- Instants are UTC ISO-8601 values; `asof` is an ISO market-date value.
- Every metric contains an explicit quality state. An unavailable metric is
  `null` and carries a reason; it is never represented as zero.
- The OpenAPI document at `/openapi.json` is the machine-readable contract.
- `scripts/web/generate_fixture_api_client.py --check` proves the checked-in
  TypeScript client types in `web/lib/generated/` match that OpenAPI contract.
- No browser route may bypass this boundary to open a local database, raw
  evidence, or generated dashboard payload.

## Local-only operation

Run the API only on a loopback host during this slice. Hosting, private data,
authentication, CORS policy, database access, provider access, and any
production API contract require their own approved work packages.
