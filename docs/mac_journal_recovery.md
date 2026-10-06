# Bounded Mac journal backup and restoration

## Scope

This is the next Mac-first recovery increment approved after the passkey package:
one complete operational-journal backup and restoration into disposable private
files. It does not change the journal, security store, runtime or hosting policy.
The existing encrypted access-setup USB image is preserved separately.

Authoritative input is the existing private `onejournal.local-web.v1` configuration
and the journal/exact financial-release files it selects. The operator is
`scripts/web/backup_mac_journal.py`; application logic is
`src/onejournal/mac_journal_backup.py`. It reuses the already tested native
disk-image, private-file and password/destination guards, not a new backup stack.

The exact file allowlist is:

- the entire operational `journal.duckdb`, including journal notes/revisions,
  accepted persisted financial results and its existing audit tables;
- the byte-identical original launcher configuration;
- only the exact portfolio and reporting release files referenced by that config;
- recovery instructions and a versioned checksum/schema/count manifest.

No broker credentials, TLS private key, passkey registry/counters, sessions or
enrollment grant is included. The separate access image covers its existing TLS
setup. Original raw evidence outside the database and security-store audit are
not copied; full evidence/security-audit disaster recovery remains separate work.
There is no recurring schedule, retention choice or production-readiness claim.

## Safe capture and verification

The operator refuses a pending journal WAL or an unavailable read-only DuckDB
lock. It never issues `CHECKPOINT`, opens the source read/write, stops a writer or
restarts a service. The read-only lock covers capture only; it is released before
slow encryption/restoration. Choose a quiet moment without simultaneous journal
editing. A busy journal fails closed rather than yielding a guessed snapshot.

Source setup, existing schema and exact release authority are validated through
the existing read-only application factory. Snapshot source/copy hashes must
match while the lock is held. All main-schema tables/views are counted, and all
column definitions are recorded. Only fixed allowlisted files are copied to
new local temporary directories, mode `0700`, with mode-`0600` files.

The tested macOS blank-image/populate/encrypted-conversion flow creates an AES-256
read-only compressed image. Its working size is based on this snapshot, not the
small access-image size. Encryption/checksum, read-only unlock, byte-exact file
restoration, complete schema/count parity and exact-release startup validation
must pass locally and again from the published USB image. The original config is
preserved verbatim; private path rebinding happens only in memory for disposable
validation, never in the live config. No endpoint is requested and no API starts.

The command reserves a new destination without overwrite. Missing USB volumes or
symlink destinations fail closed. Only already-encrypted bytes go to USB. Cleanup
removes only its own temporary files/incomplete newly reserved image; it never
erases a drive, overwrites an existing image or detaches an unrelated mount.

## Operator use

Use the existing isolated security Python environment; no installation or
dependency change is required. Run from the checkout containing these commands.
Default config is the existing private `.onejournal/passkey-access/local-web.json`
under the owner's home directory. `--web-config` can choose an explicitly selected
existing private config outside Git.

```text
python scripts/web/backup_mac_journal.py rehearse
python scripts/web/backup_mac_journal.py create --destination NEW_USB_JOURNAL_IMAGE.dmg
python scripts/web/backup_mac_journal.py verify --destination EXISTING_USB_JOURNAL_IMAGE.dmg
```

The uppercase image names are placeholders, not literal paths. Creation needs a
new `.dmg` inside the owner's selected existing directory on a mounted `/Volumes`
volume. Verification accepts an existing encrypted image without modifying it.

`rehearse` uses the configured journal read-only and an ephemeral password/image
in owner-private temporary files. It validates actual snapshot/encryption/restore
and deletes that disposable image; it does **not** create a lasting owner backup.

`create`/`verify` require the owner's interactive Terminal. The owner enters a
unique 20-plus-character password privately; creation confirms it twice. It goes
to `hdiutil` via private stdin only, never argv, environment, logs or password
files. Keep it independently of the USB; never paste it into chat. The agent does
not enter or retain the durable backup password. Password entry is an unavoidable
owner action, not an extra approval gate.

## Restoration and rollback

Rehearsal restores only into fresh temporary private directories and removes them
after verification. It never replaces the live journal or restarts either server;
there is therefore no live rollback operation for this rehearsal.

After an actual loss, restore into a **new** owner-private directory and deliberately
rebind restored journal/release paths in a separate config. Review compatible
OneJournal code and exact release validation. Recover login setup separately and
use the protected launcher; never automatically start the legacy unauthenticated
launcher or restore revoked passkeys/counters. Live restoration, replacement,
fresh security provisioning and activation remain explicit operating actions.

## Acceptance boundary

The tested command and disposable rehearsal are distinct from an owner-created,
password-controlled USB backup. Claim the latter only after the owner receives
the successful USB unlock/restoration receipt. Neither alone completes P1-10,
P1-09, Phase 1, hosted operations or full disaster recovery. Keep remaining
security-audit/raw-evidence coverage and production recovery policy visible.

## Bounded validation receipt: 2026-10-05

Four focused tests passed in the existing isolated environment: byte-exact
snapshot/read-only restoration and exclusion of security state; refusal of WAL
and write-locked source without checkpoint; malformed manifest, schema/count and
missing release-authority rejection; native AES-256 round trip, wrong-password
rejection and no overwrite. Synthetic data alone was used in these tests.

The separately approved rehearsal then used the actual privately configured
journal and its exact release files. The source WAL was absent and a read-only
lock was available. A disposable encrypted image passed local and published-copy
unlock/restoration, exact file hashes, all **82 tables/views**, complete column
definitions/count parity and the existing read-only schema/release validation.
The original configured source/copy hashes matched during locked capture. No live
write, checkpoint, endpoint request, security-state restoration or service restart
was performed. Temporary images and restored files were removed normally.

Repository/new-file privacy and whitespace checks passed. No new dependency,
full-suite rerun, Git commit/push, canonical synchronization or production
acceptance is included. The existing access USB image remains separate and
unchanged. At this rehearsal checkpoint, the owner-password-controlled USB
journal image was pending private Terminal creation. This receipt proves the
rehearsal; the subsequent lasting-backup receipt is recorded below.

## Owner USB backup receipt recorded: 2026-10-06

The owner supplied the successful `create` receipt after privately entering and
confirming the image password in Terminal. The command reported verified USB
unlock, exact files, all **82 tables/views**, schema and release validation, with
no live write or restart. The dated image filename retains `2026-10-05`; this
receipt was recorded on 2026-10-06.

A separate read-only check confirmed that the journal image exists and macOS
reports it as encrypted. The existing access recovery image also remains
present. No password was accessed and the restoration test was not repeated.

This completes the lasting encrypted USB backup and disposable restoration
verification for the bounded operational journal/exact-release scope. Keep the
password separately from the USB. Raw-evidence/security-audit recovery, hosted
operations and full disaster recovery remain open; P1-10 and Phase 1 are not
complete. Git integration is tracked separately from this recovery receipt.
