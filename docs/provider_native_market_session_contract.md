# Provider-native market-session authority and PNL-02 acceptance matrix

## Status

Accepted by the project owner on 2026-08-28 for PNL-02-T08. This document
selects the authority policy and acceptance scope. It does not implement a
resolver, call a provider, authorize credentials, activate a connection, or
make any quote eligible for valuation.

Controlling decisions are ADR-0003, ADR-0009, and ADR-0011. If this document
conflicts with an ADR, the ADR controls until the conflict is resolved
explicitly.

## Authority decision

OneJournal is a user journal connected to accounts the user owns. For each
holding, the connected account broker is the exclusive source of quote,
entitlement, delay, instrument, and market-session schedule evidence:

- Schwab evidence is resolved only through the user's Schwab connection.
- IBKR evidence is resolved only through the user's IBKR connection.
- Moomoo evidence is resolved only through the user's Moomoo connection.
- A later provider is eligible only after its API proves the same required
  capabilities through its own connection boundary.

Provider-native session evidence may come from the broker's quote response,
market-hours or trading-schedule endpoint, contract/instrument endpoint, or an
explicit combination documented by that provider. Provider-specific payloads
remain behind the adapter. The rest of OneJournal receives only a versioned,
broker-independent observation with complete source lineage.

TradingHours or another external calendar is not a PNL-02 dependency, primary
source, or fallback. OneJournal must not use IBKR, Moomoo, a generic exchange
calendar, a clock rule, or a weekday rule to repair missing Schwab evidence,
and the equivalent prohibition applies to every provider. If the connected
broker cannot supply sufficient evidence, the affected session, freshness, and
valuation remain `unavailable`; supporting that broker for freshness-dependent
valuation is blocked rather than patched with another source.

## Normalized boundary required for T09

The current `onejournal.market-session-authority.v1` value remains unchanged
for compatibility. It is not sufficient for the approved provider-native
policy because it does not bind provider, connection, or provider instrument,
and it requires every venue identifier to be a four-character MIC.

T09 must introduce a new contract version rather than reinterpret `v1`. The new
observation must bind at least:

- provider and opaque `connection_uid` matching the quote;
- provider instrument identifier and broker-independent `instrument_key`;
- provider-declared schedule scope or trading-venue identifier;
- optional MIC only when the provider supplies it or an approved deterministic
  mapping proves it; absence of a MIC must not be replaced by a guessed venue;
- IANA venue timezone and provider trading date;
- quote-time and evaluation-time phase evidence where the provider makes each
  available;
- regular, pre-market, after-hours, closed, holiday, early-close, and
  unscheduled-closure state where applicable to the instrument;
- source endpoint or response type, immutable raw locator and hash, adapter
  version, retrieval time, provider source version when available, and a
  bounded validity window; and
- deterministic observation identity.

The normalized observation is point-in-time evidence used by freshness
assessment. It is not persisted as a permanent freshness property of a quote.
Provider-native schedule responses may be cached locally only as immutable raw
evidence with an explicit validity window. An unexpired cached response from
the same provider and connection may be reused according to that provider's
documented rules. A missing, expired, conflicting, identity-mismatched, or
outage-affected response fails closed; it does not trigger another provider or
external-calendar fallback.

## Provider eligibility gate

A provider connector cannot be accepted for freshness-dependent valuation
until official documentation and bounded provider evidence establish:

1. exact instrument identity for the supported asset class;
2. quote time, retrieval time, entitlement, and live/delayed/frozen state;
3. a provider-native method to resolve the relevant trading schedule and IANA
   timezone for that exact instrument or an explicitly documented product
   scope;
4. regular and supported extended phases, normal close, holidays, early closes,
   and unscheduled closure or status behavior;
5. update frequency, response validity, rate-limit, outage, and retry rules;
6. permitted use, retention, display, and non-redistribution terms for the
   connected user's account; and
7. same-provider and same-connection lineage through normalization and
   freshness assessment.

If a provider has no reliable API evidence for a required case, the connector
must declare that capability unsupported and keep the affected valuation
unavailable. Product support may be narrower by provider and asset class, but
the UI must expose that limitation explicitly.

## Acceptance matrix

| Case | Required evidence | Expected result |
|---|---|---|
| Regular session | Same-provider schedule covers quote and evaluation instants; entitlement is usable | Regular threshold may apply |
| Pre-market or after-hours | Provider explicitly supports and identifies the phase | Extended threshold may apply |
| Normal close | Provider schedule shows the evaluation phase closed | Last eligible quote may be `market_closed_last`, never `live_fresh` |
| Holiday | Provider-native schedule identifies the non-trading date | Closed; no active polling or live classification |
| Early close | Provider-native schedule carries the irregular closing boundary | Closed after the declared boundary |
| Unscheduled closure or material halt | Provider status/schedule evidence explicitly reports it | Closed or unavailable according to the provider evidence; never inferred |
| DST transition | Provider timezone and phase instants resolve through an IANA zone | Correct UTC windows and local provider trading date |
| Quote omits session | Same-provider schedule covers the exact quote phase | Schedule observation may supply the missing session |
| Provider quote and schedule conflict in the same phase | Both facts are preserved | Unavailable and fail closed |
| Provider, connection, instrument, schedule scope, date, timezone, or evaluation mismatch | Identity validation fails | Observation rejected |
| Delayed, denied, or unknown entitlement | Provider reports non-usable entitlement or mode | Delayed or unavailable under ADR-0009; schedule evidence cannot override it |
| Schedule response missing, expired, or unavailable | No valid same-provider observation exists | Unavailable; no fallback |
| Cross-provider or external-calendar substitution | Authority source differs from the quote's connected broker | Observation rejected |

Contract tests must cover every row, including negative and outage behavior,
without credentials or network access. Initial Schwab real-evidence acceptance
must then include an official equity quote, an official provider-native
market-hours or schedule response bound to that quote's connection and
instrument scope, a listed-equity-option shape, and provider-native schedule
evidence containing normal, holiday, and early-close dates. A live unscheduled
closure need not be manufactured; its response mapping and fail-closed absence
must be proven from the official provider contract plus synthetic regression
fixtures. IBKR, Moomoo, and later connectors repeat this matrix when their
rollout is approved; they are not required to close the initial Schwab scope.

## Source evidence reviewed

- Schwab's authenticated Market Data Production specification remains the
  authoritative provider contract. The bounded official equity response
  already preserved in private evidence supplied no `marketSession`, so a
  separate Schwab-native market-hours or schedule response still has to be
  proven: <https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production>.
- IBKR officially documents a contract schedule endpoint that returns exchange,
  timezone, and trading times for up to one month. This establishes a plausible
  future IBKR-native adapter source, not authority for Schwab quotes:
  <https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-contracts/get-trading-schedule>.
- TradingHours documents authenticated bulk downloads and annual
  per-application licensing. It was evaluated and rejected as a PNL-02 source,
  not treated as free or silently retained as a fallback:
  <https://docs.tradinghours.com/4.x/endpoints/download> and
  <https://www.tradinghours.com/data>.
- Moomoo and any later provider must pass the provider eligibility gate from
  current official API documentation and bounded evidence when its rollout is
  approved. No current T08 decision claims that it has passed.

## Approval boundaries

T09 may implement the new provider-neutral value contract, provider interface,
offline adapters, fixtures, and tests locally after model reassessment. That
does not authorize a Schwab, IBKR, Moomoo, or other provider call.

Each credential installation or use, token refresh, live provider capture,
private-evidence transfer, runtime database migration, connector activation,
deployment, synchronization, push, or production operation remains a separate
explicit approval. OneBot remains only the temporary Schwab evidence bridge
until the separately approved single-owner cutover.
