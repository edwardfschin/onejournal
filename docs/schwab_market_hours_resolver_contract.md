# Schwab market-hours resolver contract

## Status

Approved by the project owner on 2026-08-29 for the offline PNL-02-T14
source-to-authority correction. This contract implements no provider call,
credential access, private-evidence write, database write, connector activation,
deployment, synchronization, or order capability.

## Source-faithful correction

Schwab's observed market-hours response provides exact product/date identity,
`isOpen`, and offset-aware phase boundaries. It does not provide an IANA
timezone identifier, and its closed-market sentinel does not identify whether
the cause is a holiday or an unscheduled closure.

The provider-neutral authority contract therefore accepts
`closed_unspecified` only with a `closed` market session. It prevents a
provider-confirmed closure from being relabelled as a holiday or unscheduled
closure. Freshness may treat the session as closed, but presentation and audit
must preserve the unspecified reason.

The approved Schwab mappings are:

| Provider market | Product | OneJournal asset class | Schedule scope | IANA timezone |
|---|---|---|---|---|
| `equity` | `EQ` | `stock` | `schwab:market-hours:equity:EQ` | `America/New_York` |
| `option` | `EQO` | `option` | `schwab:market-hours:option:EQO` | `America/New_York` |
| `option` | `IND` | `option` | `schwab:market-hours:option:IND` | `America/New_York` |

This mapping names the timezone and product scope only. It is not a market
calendar and does not supply phase times, trading dates, holidays, or closures.
Every provider timestamp's wall time and UTC offset must match the mapped IANA
zone for that instant. A mismatch fails closed.

## Schedule classification

`schwab-market-hours-json-v1` remains the lossless response parser.
`schwab-market-hours-resolver-v1` then:

- resolves phases only from the exact provider intervals for the quote and
  evaluation dates;
- classifies an open schedule as `regular` only when its local phase signature
  matches the checksum-bound normal reference;
- classifies `early_close` only when the regular phase starts normally and ends
  earlier, all non-regular pre-close phases match, and any provider-declared
  after-hours phase begins at the shortened regular close and also ends earlier;
- preserves the exact provider closed sentinel as `closed_unspecified`;
- rejects unsupported schedule variations instead of guessing; and
- derives closed gaps only between exact provider phases and the mapped local
  day boundary.

No external calendar, another broker, weekday rule, or clock-only schedule may
replace missing provider evidence.

## Combined lineage

The resolver accepts only schedule files whose SHA-256 digests are members of a
checksum-bound combined manifest. The resulting
`onejournal.provider-market-session-authority.v2` value uses:

- `source_response_type=combined`;
- the combined manifest's logical private raw path and SHA-256;
- the latest retrieval time and earliest validity limit among every schedule
  member used; and
- the resolver version, provider source version, exact connection, quote,
  instrument, product scope, and evaluation instant.

Missing manifest membership, changed hashes, invalid paths, duplicated market
dates, expired evidence, or missing exact-date schedules fail closed.

## Current T14 evidence result

The checksum-bound `PNL-02-T14-SCHWAB-20260828-04` schedule files validate for
the approved `EQ` and `EQO` scopes, including the observed daylight-saving
offsets and shortened-session boundaries. The official equity and option quotes
are dated 2026-08-28, while the bundle's schedules are dated 2026-08-31,
2026-09-07, and 2026-11-27. The resolver therefore rejects both actual quotes
because no exact 2026-08-28 schedule exists. That is the intended fail-closed
result.

T14 still requires one separately approved same-date quote-and-schedule evidence
capture before real provider-session authority can be accepted. This document
does not authorize that provider call or any later T15 action.

## Validation and rollback

Synthetic tests cover stock and listed-option normal phases, shortened regular
and extended phases, closed unspecified days, IANA offset conflicts, manifest
membership and path/hash failures, provider/connection/asset mismatches,
validity expiry, and missing exact-date evidence. The private `-04` bytes are
checked read-only outside the automated suite and are never copied into Git.

Before commit, rollback is removal of the resolver, tests, and this approved
contract correction. No external or persisted state needs restoration.
