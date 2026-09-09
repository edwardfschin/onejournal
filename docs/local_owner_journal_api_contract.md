# OneJournal local-owner journal API v5

## Scope

`onejournal.local-owner-journal.v5` is the WEB-W06 journal boundary for a
private local owner. It exposes existing journal domain behavior through a
server-selected DuckDB database and a loopback-only launcher. WEB-W07
additively registers the separately versioned broker-current portfolio route
described below. Neither boundary is a hosted service, authentication design,
broker connector, or raw-evidence browser.

## Routes

- `GET /api/v5/local-owner/journal/search` — server-side journal/episode search;
  entry matches contain metadata only, never title or body prose.
- `GET /api/v5/local-owner/journal/review-queues` — deterministic reason-coded
  review queues without private narrative.
- `GET /api/v5/local-owner/journal/trades/{episode_uid}` — one lifecycle,
  distinct instruments, exact Schwab executions, and its active private entries.
- `GET /api/v5/local-owner/journal/entries/{entry_uid}` — one intentionally
  opened current active entry, including its private prose.
- `POST /api/v5/local-owner/journal/reviews` — append a review event and update
  the existing compatibility projection.
- `POST /api/v5/local-owner/journal/entries` — append entry revision 1.
- `POST /api/v5/local-owner/journal/entries/{entry_uid}/revisions` — append a
  complete immutable next revision.

Every response declares `contract_version: onejournal.local-owner-journal.v5`
and `mode: local_owner`. No local-owner route is registered by the demo fixture
application.

## Broker-current portfolio route

- `GET /api/v1/local-owner/portfolio/current` returns
  `onejournal.api.broker-current-position-valuation.v1` only when the process
  starts with an exact owner financial-release authorization and its named run
  exists in the server-selected database.
- No authorization returns HTTP 503 with no positions or values. A malformed,
  unsafe-permission, missing-run, or fingerprint-mismatched authorization
  prevents authorized startup.
- The response preserves explicit as-of, retrieval/evaluation times, source
  contract, basis method, snapshot/run/fingerprint/acceptance identity and UTC
  acceptance-time lineage, currency quantum, per-metric availability counts,
  position states, and independently gated complete totals.
- It never reads or reinterprets the historical bounded FIFO `48 eligible / 10
  unavailable` evidence as a current portfolio total. It never fabricates lots,
  realized P&L, holding periods, or tax treatment.

## Privacy and authority rules

- The browser never supplies a database path, SQL, provider request, token,
  account identifier, raw-evidence path, or storage key.
- Trade/read payloads omit source account identifiers. Journal prose is returned
  only where the local owner intentionally opens private journal content.
- Trade summaries expose the latest migration-0020 reconciled lifecycle status,
  quality, and reason. The status uses Schwab terminal events and the complete
  current-position snapshot. Incomplete-history scopes remain visible, enter
  the incomplete queue, and never acquire fabricated financial aggregates.
- Migration-0019 episode strategy comes from distinct instruments and opening
  direction, never execution count. Lifecycle detail calls the source rows
  `executions`, not strategy legs, and exposes exact time, quantity, price,
  multiplier, commission, fees, currency and Schwab net cash movement.
- Every exposed execution cash movement is independently recalculated and must
  match its exact Schwab transaction before the projection or API is usable.
  It is cash movement, not realized or unrealized P&L.
- A result row is an instrument lifecycle unless the source fills carry an
  explicit approved episode group. The API exposes `asset_class`, exact option
  contract summary, and current-position reconciliation state in search and
  lifecycle views; review-queue rows also expose asset class and the exact
  instrument summary. An option leg therefore cannot be mistaken for stock
  merely because both share an underlying ticker.
  It does not merge rows by ticker or infer an economic spread from a multi-leg
  Schwab order; ADR-0005 explicitly forbids that shortcut.
- Search, queue, and lifecycle responses include only presentation groups that
  satisfy ADR-0026. Each group comes from a filled Schwab `VERTICAL` opening
  order whose exact two option episodes independently agree on underlying,
  expiry, option type, currency, distinct strikes, opposed directions, and
  equal quantity. Repeated scaling orders for the same pair consolidate into
  one group. Order/account identities are omitted, and the two underlying
  episodes remain separate journal and financial records.
- Group summaries expose opening date, expiry, quantity, exact net opening cash
  movement, commissions, fees, member average opening fills, and member cash
  paid/received. They do not expose Mark or P&L; those remain governed by the
  later accepted valuation and lifecycle financial boundaries.
- Search, queue, and lifecycle responses include ADR-0027 lifecycle stories
  derived from exact projected Schwab executions. An instrument's opening and
  closing executions appear as ordered phases with explicit open/close
  instruction, time, quantity, average fill, exact cash movement, commissions,
  fees, currency, and execution count.
- A short-option assignment or long-option exercise links to the exact resulting
  stock execution only when the same private account, UTC instant, underlying,
  strike price, contract quantity times multiplier, expected direction, and
  projected journal executions form one unique structured match. Provider
  account/transaction identities remain private. Ambiguous candidates remain
  unlinked, and neither lifecycle is merged or financially promoted.
  The matching stock execution may be opening or closing; its broker position
  effect must agree exactly with the projected execution. A negative stock
  quantity from a short-call assignment is presented as stock called away.
- A closed option exposes `expiration_indicated` only when the latest accepted
  Schwab receive-and-deliver lifecycle evidence contains an exact expiration
  event that matches the private account, option contract, residual FIFO
  quantity, expiry date, reconciled terminal-event state, and projected
  lifecycle. The payload keeps the contract expiry and Schwab posting instant
  distinct, declares `review_required`, and exposes no provider event identity.
  It does not claim `worthless` or `out_of_the_money`; absence of a matched stock
  settlement is reported only as the bounded relationship result.
- A search result may omit a standalone stock card when that exact stock
  lifecycle is already reachable beneath a displayed assignment or exercise.
  This is presentation de-duplication only: the stock lifecycle remains an
  independent journal record and exact detail resource.
- Audit records store an operation identity, action, stable resource identity,
  outcome, UTC timestamp, and SHA-256 request fingerprint only. They never
  store review notes, entry bodies, raw evidence, account identifiers, or
  credentials.
- `X-OneJournal-Operation-Id` is a required UUID for every write. The same UUID
  and request is replay-safe; reuse with a changed request fails closed.
- The API delegates validation, append-only behavior, and compatibility writes
  to the existing journal domain services. It introduces no P&L calculation,
  broker operation, or order capability.
- The broker-current route delegates exact-run read-back and serialization to
  the accepted repository/API contracts. A successful read writes one
  privacy-safe migration-0022 release audit containing no account, instrument,
  financial value, raw path, credential, or provider payload.

## Operation and migration boundary

Use `scripts/web/run_local_owner_journal_api.py --db <private-db>` only after
the normal private-database backup and migration approval workflow. The script
requires a regular, non-symlink mode-`0600` migration-0020-or-later database with a
complete execution-first projection and lifecycle reconciliation, binds `127.0.0.1` only,
does not apply migrations, and does not reveal the database path in an API
response. The local process serializes database access so simultaneous reads,
writes, and retries cannot race its audit and receipt transactions. The
launcher never applies migrations. For the owner-accepted WEB-W07 local scope,
the separately approved backup, rehearsal, and migration workflow advanced the
mode-`0600` operational journal through migration 0023 before the launcher was
started. Starting this worktree or launcher must not migrate any other journal.

Add `--broker-current-authorization <private-authorization.json>` only after
migration 0023 and the exact accepted broker-current result have been
separately approved and persisted in that database. Omitting the option keeps
the portfolio route unavailable while leaving the accepted WEB-W06 journal
boundary unchanged.

Add `--reporting-authorization <private-report-authorization.json>` only after
migration 0024 and an exact owner-accepted Phase 1 report release have been
separately persisted. The file uses contract
`onejournal.phase1-report-release-authorization.v1`, mode `0600`, a mode-`0700`
parent directory, and exact release UID, release fingerprint, and owner-
acceptance UID binding. Omitting it keeps the reporting routes unavailable.
Supplying it does not calculate or persist a report. The launcher reads no
provider credential or raw evidence.

For the browser checkpoint, start the API and web development server in two
separate local terminals. Set `ONEJOURNAL_LOCAL_API_URL=http://127.0.0.1:8765`
only for the web process, then open `/local/journal`. Vite proxies only the
`/api/v5/local-owner` and `/api/v1/local-owner` paths and binds its own
development server to `127.0.0.1`.
If that explicit target is absent or the API is unavailable, the page shows an
unavailable state and never substitutes synthetic journal or portfolio data.
The journal and trade entry points are `/local/journal` and `/local/trades`;
the broker-current portfolio slice is `/local/portfolio`. The former
`/journal/local` and `/portfolio/local` paths redirect to their canonical local
routes and must not appear in navigation or operator instructions.

When migration 0021 has an activation for an account, all journal search,
queues, trade inspection, execution details, vertical groups, and lifecycle
stories resolve the latest append-only materialization revision. Prior episodes
remain stored but are excluded from current API lists and trade lookup. An
unchanged episode identity retains its review and journal-entry relationships;
a changed identity does not silently inherit them.

Hosted access, authentication, CORS/origin policy, session controls, and
multi-owner authorization remain blocked on WEB-W10 and OPS-06.

## WEB-W07 operational acceptance

The project owner accepted the demonstrated private single-owner local-only
WEB-W07 scope on 2026-09-07. The exact authorized run
`broker-current-position-valuation:e628da6f62242a46239171ba359c0798b66ec3f783fa81c6137f132cb44a3266`
and result fingerprint
`4993902f4bb9aa6e6324948c956cb1f28f367b7bcab97d616c6d990d1456e3e3`
are persisted through migration 0023 as one run, 58 position snapshots, 58
valuations, and one complete-total row. One successful real loopback read wrote
exactly one value-free accepted audit row. Desktop, tablet, and mobile browser
checks passed without horizontal overflow, and the stopped-API check displayed
the explicit unavailable state without cached, synthetic, or FIFO fallback.
The later owner-directed route correction established `/local/portfolio`,
`/local/trades`, and `/local/journal` as the canonical entry points, verified
legacy redirects, and kept the API stopped so no additional read audit was
created.

This acceptance does not authorize or claim continuous provider acquisition,
credential ownership, authentication, hosted access, VPS work, deployment,
broader or realized P&L, trading, commit, or push.
