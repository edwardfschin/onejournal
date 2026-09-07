# Private OneJournal workstation handoff

`onejournal.private-workstation-handoff.v1` moves owner-private OneJournal state
between two trusted Macs without treating Git as a private-data transport.

## Safety model

The operator is deliberately one-way and explicit. `push` means this Mac is the
source; `pull` means the SSH host is the source. It never chooses the newer
database from timestamps and never performs bidirectional conflict resolution.

Before planning or applying, both vaults must be existing absolute non-symlink
directories with mode `0700`. Every directory below them must be `0700`; every
file must be a regular non-symlink mode-`0600` file. A DuckDB WAL or any open
handle on the operational database blocks the handoff.

Python `__pycache__` directories are runtime debris and are excluded. The exact
operational DuckDB `.tmp` directory is also excluded only when empty; a
non-empty temp directory blocks the handoff as possible active database state.

Immutable evidence is unioned additively. Missing files are copied, files that
exist only at the destination are retained, and nothing is deleted. If the same
relative path exists with different bytes, the entire transfer is blocked.
Both local and remote transfer processes use a restrictive `077` creation mask;
the operator then validates and fixes the exact added file and parent modes
before advancing beyond the immutable-evidence stage.

The operational database is special. It is copied to a new staging path,
SHA-256 verified, and atomically moved into place only after rechecking source
and destination. If the destination already has a different database, an exact
mode-`0600` backup is created first under the private `journal/transfer-backups`
directory. Transfer locks prevent two handoff operators from running at once.

## MacBook to iMac

Close the OneJournal API, DuckDB tools, notebooks, and any process using the
private database on both Macs. From the MacBook repository, plan first:

```bash
python scripts/private/sync_onejournal_private_state.py plan \
  --direction push \
  --remote imac-onejournal
```

Review the privacy-safe counts and require `status=ready`. Then apply the exact
printed fingerprint. The fingerprint also binds the exact operator bytes, so a
script or connection change between planning and applying makes the plan stale:

```bash
python scripts/private/sync_onejournal_private_state.py apply \
  --direction push \
  --remote imac-onejournal \
  --plan-fingerprint <exact-plan-fingerprint>
```

If the SSH alias identifies the correct iMac and key but its configured network
address is unavailable, an already-trusted alternate address can be selected
without accepting a new host key:

```bash
python scripts/private/sync_onejournal_private_state.py plan \
  --direction push \
  --remote imac-onejournal \
  --ssh-hostname <alternate-address> \
  --host-key-alias <existing-known-hosts-name>
```

Use the identical connection options for `apply`. `--host-key-alias` is allowed
only with `--ssh-hostname`; this ensures the alternate route must present the
host key already trusted for the named Mac.

## iMac to MacBook

The reverse uses the same script from the iMac after the repository has been
updated there. It requires an SSH alias or host that authenticates to the
MacBook:

```bash
python scripts/private/sync_onejournal_private_state.py plan \
  --direction push \
  --remote macbook-onejournal
```

Using `push` from the machine being left makes source authority visible. `pull`
is available when it is more convenient to initiate the handoff from the
machine being entered, but the named remote machine then becomes authoritative.

## Operating rule

Only one Mac may write the operational journal between handoffs. Finish work,
close all database users, run plan and apply, confirm `status=verified`, and
only then open OneJournal on the other Mac. Git commit/push/pull and this private
handoff are independent operations.
