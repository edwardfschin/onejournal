# Mac source-evidence and security-audit recovery

This is a third, separate Mac-only recovery image. The existing access image
contains local setup but no passkeys, and the existing journal image contains
the operational database and exact release files. Neither contains the original
external raw files or the separate security audit.

`scripts/web/backup_mac_evidence_audit.py` selects only JSON files whose SHA-256
fingerprints appear in the journal's persisted Phase 1 Schwab v1/v2 family
records or validated v3 snapshot assemblies, including the exact v3 artifact
itself and every family's manifest/raw lineage (quotes and sessions included).
It fails if a recorded fingerprint is missing or a matched
file is not owner-private. It exports only the security store's timestamp,
fixed action and fixed outcome audit fields. It checks the store's existing
owner/journal/localhost binding and requires a clean, unlocked store. It never
copies the security database, credential IDs, public keys, counters, enrollment
grants, sessions or failures table.

The operator creates an AES-256 encrypted macOS disk image, writes only that
encrypted image to a new file on a mounted USB, then unlocks the **USB copy**
and restores every selected file into a disposable owner-private directory.
Hashes, manifest membership and audit row counts must match. The command does
not stop or restart the site, modify a database, restore over live files or
change a passkey. The image is point-in-time: new imports or later audit events
need a new image. It complements, not replaces, the two existing recovery
images. It is not hosted/production disaster-recovery acceptance.

## Owner operating step

Use the locked Mac passkey Python environment. Keep the protected site stopped
for this command; its API otherwise holds the security store's writer lock.
The destination must be a **new** `.dmg` path on the mounted USB. Enter a
unique 20+ character image password privately when prompted. Do not put it in
the command, chat, Git or the USB. Keep it separately. After the command says
the encrypted USB image and disposable restore passed, restart the protected
site from its approved launcher and verify a normal passkey sign-in.

```sh
python scripts/web/backup_mac_evidence_audit.py create \
  --raw-root /absolute/private/evidence \
  --destination '/Volumes/YOUR_USB/OneJournal/new-evidence-audit-recovery.dmg'
```

To recheck an existing image without touching the live site or databases:

```sh
python scripts/web/backup_mac_evidence_audit.py verify \
  --destination '/Volumes/YOUR_USB/OneJournal/new-evidence-audit-recovery.dmg'
```

The verification command reads the image only; no live source files are read.
The image's recovery instructions require restoring into a new owner-only
directory, verifying hashes and journal lineage, and using fresh offline
passkey enrollment rather than restoring old security state.

## Validation and limits

- Synthetic encrypted-image round trip, wrong-password and no-overwrite checks
  exercise the native macOS image mechanism.
- The live journal's current persisted lineage has 25 distinct fingerprints,
  represented by 27 private files. This count is an observation at the time of
  preparation, not a hard-coded backup list.
- The running site's security database cannot be opened consistently by a
  second process. Do not infer a live-audit capture or lasting USB receipt from
  the synthetic test. Record those only after the protected site is stopped,
  the owner runs the command, and its USB restoration succeeds.
- This scope does not assert that all unimported private evidence or future
  broker/market-data captures are backed up. It covers the explicitly
  persisted Phase 1 Schwab v1/v2/v3 assembly lineage only.

## Refreshed-release backup preparation: 2026-10-12

The owner requested the remaining useful Mac-first work and an updated
off-device backup. The earlier evidence selector covered only legacy family
tables; a new image would silently omit newer persisted snapshot evidence.
The focused correction unions legacy lineage with exact validated snapshot
artifacts and all their source families. It reuses the authoritative migration,
checksum and artifact validator, refuses missing snapshot lineage when its
migration is applied, and leaves source state unchanged. Images keep the same
manifest format; earlier images remain verifiable. No financial calculation,
migration, credential or security-policy change is included.

Five focused synthetic checks cover legacy privacy behavior, missing files and
locked audit refusal, complete new/legacy lineage, artifact tampering and
missing applied-schema lineage. A read-only check located every required file
for the current persisted evidence, without changing the source journal.
Encryption is unchanged and will be validated by actual owner-operated image
creation, not a repeated native test cycle. Detailed receipts remain private.

Create new journal and evidence/audit images using the **active publication
configuration**, not the older default. Stop only the protected site's owned
process for capture and restart the same installed release/configuration
afterwards. Enter passwords only in the owner's Terminal. Preserve existing
images; no overwrite or retention cleanup is authorized. The unchanged
access/TLS image does not need recreation merely because financial data
advanced. No lasting refreshed image is claimed until both owner-operated USB
restoration checks succeed.

## Owner-verified refresh receipt: 2026-10-12

The owner supplied successful creation receipts for both new encrypted images:
journal unlock/restoration, schema and exact release validation passed, and the
evidence/audit image passed disposable restoration of its selected files and
value-free events. Independent read-only checks confirmed both images are
owner-private and encrypted. Earlier images remain present; no password was
read and no redundant encryption/restoration cycle was run.

The private convenience wrapper then reported "incomplete" because its extra
whole-file byte comparison failed after both image verifications. That warning
does not negate their successful restoration, but its original proof that all
source bytes stayed unchanged is **not claimed**. Configuration, authorizations
and TLS bytes matched; database bytes differed. Inspection identified an
unsafe quiescence assumption: Uvicorn closes its listener before draining
requests and the access store closes afterwards. The wrapper now waits for
the owned process to finish before taking its byte baseline; one synthetic
delayed-shutdown regression passed without touching the real service.

The private completion receipt records the verified images and the failed
wrapper proof separately. The same protected site restarted and its HTTPS page
responded. This completes the dated off-device refresh, not recurring backup,
retention policy, cross-Mac/hosted recovery or full Phase 1 acceptance.

## Owner USB receipt: 2026-10-06

The owner entered a new password privately in Mac Terminal. The command
reported an AES-256 USB image and disposable restoration of **27 exact source
files and 20 value-free audit events**. An independent read-only check found
the image on the mounted USB, owner-only (0600) and encrypted. No live journal
or security-database write was performed by the backup. The original protected
site was stopped cleanly for the audit snapshot and restarted with the same
local configuration; its HTTPS Reports page returned 200 after restart. The
owner subsequently confirmed that normal passkey sign-in still works.

The image remains point-in-time. It does not prove recurring backup, recovery
on another Mac, a hosted/VPS restore, or full Phase 1 completion. New imports
and subsequent security events are not included until another image is made.
