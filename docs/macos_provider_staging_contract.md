# Temporary macOS provider staging contract

## Approved scope

The OneJournal project owner approved the current Mac on 2026-08-29 as the
temporary local-only PNL-02-T15 staging host. The approved target uses macOS
Keychain, has no public listener, mounts no operational DuckDB journal, and must
not receive or copy a token from OneBot. It remains distinct from the OneBot VPS.

This approval selects a target and security boundary. It does not authorize
credential installation, OAuth authorization, token refresh, provider calls,
private-evidence creation, database access, OneBot retirement, activation,
commit, push, synchronization, or deployment.

## Repository boundary

`config/marketdata.yaml` contains `onejournal.macos-provider-staging.v1`. Its
checked-in state is fail-closed:

- staging disabled;
- credential installation disabled;
- provider calls disabled;
- token refresh disabled;
- public listener disabled;
- operational journal database unmounted; and
- private capture storage limited to the external private vault.

`src/onejournal/provider_connectors/macos_staging.py` provides two isolated
mechanisms for a later approved runtime:

1. A macOS Keychain generic-password store whose account key is the opaque
   OneJournal connection UID. Secret bytes are supplied through standard input,
   never command arguments, and ordinary representations and failures are
   redacted. Create does not overwrite; refresh replacement requires the current
   generation and owner epoch.
2. A private `0700` local lock root with one `0600` advisory-lock file per opaque
   provider connection. The lease binds the provider, connection, and owner
   epoch and prevents concurrent local owners.

The concrete Keychain runner accepts only the exact find, create, and
generation-replacement generic-password command shapes for the fixed OneJournal
service. The module has no HTTP client, OAuth flow, listener, scheduler, CLI,
DuckDB dependency, account operation, or order operation. Repository policy is
checked before any credential read, install, token release, or refresh write.

## Operational sequence and remaining gates

The operational cutover remains break-before-make:

1. Rehearse the exact provider-disabled artifact on this Mac and prove its
   identity, process boundary, disabled policy, absence of credentials, lack of
   listeners and DuckDB mounts, and clean rollback.
2. Confirm the current authenticated Schwab terms acknowledgement and approve
   the exact local private-evidence and provider-call scope.
3. Under a separately bounded cutover approval, prove every OneBot Schwab call
   and refresh path inactive and the old token inaccessible.
4. Only after that owner gap, complete a fresh Schwab authorization directly
   into the OneJournal Keychain item. Do not import an OneBot token.
5. Prove the target first while provisioned but provider-call and refresh gates
   remain disabled; then separately approve bounded activation.
6. Capture authoritative four-phase evidence and validate it with
   `onejournal.provider-connection-cutover.v1`.

Any failure stops the sequence. Rollback first disables OneJournal provider
calls and refresh and makes its credential inaccessible. OneBot cannot be
reactivated until the reverse owner gap and separate reauthorization are proven.

## Validation status

Automated tests use only synthetic records, a fake Keychain command runner, a
temporary private lock directory, and repository configuration. They prove
policy fail-closed behavior, canonical secret records, no secret command
arguments, create-without-overwrite, stale-generation rejection, expiry
rejection, owner-epoch binding, and exclusive local leasing. They do not access
the actual macOS Keychain or establish operational T15 acceptance.
