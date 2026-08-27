# Retired OneJournal Schwab Historical Fetch Operator

## Status

The former OneJournal Schwab historical fetch operators are retired and their
active scripts have been removed. This document intentionally contains no live
command, credential configuration, token path, or provider procedure.

The current OneJournal runtime is credential-free and must not call Schwab,
refresh a token, discover an account, or acquire broker history. During the
bounded PNL-02 evidence step, OneBot/VPS is only a temporary single-owner
Schwab bridge. The target architecture instead uses an isolated OneJournal
provider connector after a separately approved single-owner cutover.

## Preserved evidence and offline planning

Retiring the operators does not delete or alter existing raw evidence,
normalized records, audit artifacts, or journal database state. Those remain
subject to their existing evidence, lineage, reconciliation, and private-vault
contracts.

`scripts/journal/plan_schwab_raw_history_backfill.py` remains only as an offline
acquisition-request planner. It can split a reviewed date range into bounded
windows and estimate request counts, but it has no network, token, file-write,
or database capability and grants no broker authority.

## Future historical evidence

Do not recreate a generic OneJournal history fetcher. When an accepted product
or reconciliation requirement identifies a precise missing evidence scope, use
separate approval gates for:

1. the exact case, date bounds, endpoint scope, and evidence required;
2. a smallest-scope approved provider connector or temporary evidence producer
   operating under its credential and provider controls;
3. private, checksum-validated bundle transfer; and
4. OneJournal validation, normalization, reconciliation, and import outside
   the credential boundary.

Each gate remains independent. Planning does not authorize provider access;
capture does not authorize transfer or import; and imported evidence does not
by itself establish completeness, financial acceptance, or production
readiness.

Once the target OneJournal provider plane is approved, the connector—not the
journal, financial engine, or UI—owns provider access. OneBot must no longer use
the Schwab token after that cutover.
