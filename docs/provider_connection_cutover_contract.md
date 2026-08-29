# Provider connection single-owner cutover contract

## Purpose

`onejournal.provider-connection-cutover.v1` is the credential-free evidence
boundary for PNL-02-T15. It validates the ordering required by ADR-0012 and the
staging isolation required by ADR-0014. It is provider-neutral so later IBKR,
Moomoo, and other connectors can use the same owner transition without adopting
Schwab OAuth details.

The implementation is
`src/onejournal/provider_connectors/cutover.py`. It is a pure validator: it does
not inspect a host, stop a service, change configuration, access or refresh a
token, call a provider, write evidence, mount a database, or activate a
connector. An operator must establish each supplied fact from the actual
configured service, process, scheduler, credential backend, and network
boundary. A structurally valid record is not operational acceptance by itself.

## Required sequence

Every forward cutover and rollback uses the same four phases. For rollback, the
currently active OneJournal owner is the source and the separately reauthorized
former owner is the target.

1. `source_active`: the source has credential, quote-call, and refresh
   capability; the target has none.
2. `owner_gap`: neither source nor target has credential, quote-call, or refresh
   capability.
3. `target_provisioned_disabled`: the source remains retired; the target has a
   newly authorized credential generation and new owner epoch, while quote calls
   and refresh remain disabled.
4. `target_active`: the source remains retired; the same target owner epoch and
   credential generation become the sole active call and refresh path.

Observations must be strictly ordered UTC instants and bind unique SHA-256
evidence. Source/target owner and host identities must remain stable and the two
hosts must differ. The target cannot reuse the source owner epoch or credential
generation. Any overlap, missing owner gap, reordered phase, identity change,
lineage change, public listener, or operational journal mount fails closed.

The record also requires the exact cutover approval, hosted-data authorization,
and current provider-usage acknowledgement references. These are references,
not substitutes for externally proving that the approvals and evidence are
authentic and current.

## T15 operational gates

The offline validator closes only the contract/rehearsal gap. T15 remains
blocked until all of the following are separately established and approved:

1. A dedicated OneJournal-owned staging host or VM, distinct from every OneBot
   runtime, with its exact host identity, service identity, deployment method,
   secret backend, provider egress allowlist, private storage, backup, restore,
   and rollback procedure approved.
2. A replacement provider-use profile approved after authenticated review of
   the applicable Schwab terms and exact data products. The current repository
   profile has `hosted_storage_allowed: false` and cannot authorize live capture
   on a staging host.
3. A provider-disabled staging rehearsal proving artifact identity, no
   credentials or live data, no public listener, no operational DuckDB mount,
   secret-safe logs, service isolation, and clean removal.
4. A bounded cutover approval covering the exact OneBot retirement paths,
   credential invalidation method, fresh OneJournal authorization, target owner
   epoch, first provider call, evidence locations, stop conditions, and rollback.
5. Fresh operational evidence for all four phases from authoritative runtime
   locations. Logs alone are insufficient when service, scheduler, process,
   credential-store, or network state can be inspected directly.

OneBot's usable Schwab token must not be copied into OneJournal. It must first
lose every call and refresh path and the former credential must be revoked or
made inaccessible. Only then may OneJournal receive a newly authorized
credential generation. No failure permits silent OneBot reactivation.

## Validation

`tests/test_provider_connection_cutover.py` covers valid forward and rollback
sequences plus dual ownership, missing gap, reused lineage, host collision,
time/phase disorder, target isolation, credential/capability inconsistency, and
evidence-hash failures. All cases are synthetic and credential-free.

No provider call, credential access, host change, private-evidence write,
database write, deployment, synchronization, or cutover is performed by this
contract or its tests.
