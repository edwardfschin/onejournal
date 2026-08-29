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

The checksum-bound `PNL-02-T14-SCHWAB-20260829-06` bundle preserves manifest
SHA-256 `a518edd8869b4e3cc41fec9355f30fb109d5c241a1fb567003adb2e7dae74317`.
Its official equity and option quotes and normal `EQ`/`EQO`/`IND` schedules are
all dated 2026-08-28; its closed and shortened schedules remain 2026-09-07 and
2026-11-27. All member hashes, offsets, phases, and exact scope mappings pass.
The option produces actual combined v2 authority and `market_closed_last`.
The equity's observed `securityStatus=Closed` is preserved by
`schwab-quote-json-v2` as `data_mode=frozen` with session unknown; it becomes
`market_closed_last` only when this exact v2 authority reports the evaluation
session closed and remains ineligible while a supported session is open.

This evidence closes the same-date resolver gap. It does not authorize T15,
provider activation, persistence, migration, or production use.

## Validation and rollback

Synthetic tests cover stock and listed-option normal phases, shortened regular
and extended phases, closed unspecified days, IANA offset conflicts, manifest
membership and path/hash failures, provider/connection/asset mismatches,
validity expiry, missing exact-date evidence, and frozen quotes before and after
effective market close. The private `-06` bytes are checked read-only outside
the automated suite and are never copied into Git.

Before commit, rollback is removal of the resolver, tests, and this approved
contract correction. No external or persisted state needs restoration.
