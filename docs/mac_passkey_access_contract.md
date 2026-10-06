# Mac passkey access prototype

## Scope and current state

ADR-0031 initially selects an isolated Mac-only owner-access prototype. The
owner subsequently approved trusted HTTPS, private enrollment, USB access-setup
recovery and the bounded existing-journal Mac switchover below. Device/session
acceptance is distinct from that implementation/activation authority.
Use disposable journal/security state and separate ports for tests. Never copy private
credentials, enrollment secrets, TLS keys or security databases into Git/chat.
No financial method, journal schema, release fingerprint or broker authority
changes. The original local launcher remains unchanged and is not hosted-ready.

## Data and request flow

Offline provisioning -> dedicated security store and expiring enrollment file
-> browser WebAuthn -> server verification -> volatile cookie session -> existing
private API -> existing journal/report authority. The frontend hides private
children until a session is verified. The server gate is authoritative: direct
API requests, exports, legacy routes and documentation also require access.
Unauthenticated requests cannot reach financial readers or append journal audits.

`/api/v1/local-owner/access` provides session status, registration options/verify,
login options/verify and logout. Only status and ceremonies are anonymous; they
cannot create an owner or read financial state. POSTs require exact Origin and
JSON; private writes/logout and authenticated registration require session CSRF.
No credentials/tokens/financial values appear in errors or security audit.

The separate `onejournal.mac-passkey.v1` security schema contains `access_meta`,
`passkeys`, `access_failures`, `access_audit`. Schema v1 is created only by offline
provisioning; an unknown schema/binding fails closed, with no automatic upgrade.
Keys are public; owner identity is opaque and journal binding is a resolved-path
digest. Enrollment is stored only as a hash. Cookies, sessions and challenges
are not persisted. Failed attempts survive restart until their 15-minute window
expires. Security-store failure does not grant legacy access.

Session status reports the seconds until the earlier of idle or absolute
expiry. The browser hides private views at that deadline and checks it again
on focus after sleep. The server gate remains authoritative for every private
request. After confirmed logout, an origin-scoped browser signal also hides
already-open private views in other tabs immediately; it carries no credential
or financial value. A browser without this feature still loses server access
immediately and its other tabs clear on their next session check.

Defaults: 15-minute idle/8-hour absolute session, two-minute single-use challenge,
ten-minute one-use enrollment, five failed attempts per 15 minutes, five passkeys,
32 simultaneous challenges/sessions. Session-status polling never extends idle
expiry. Restart revokes all sessions. Add a backup passkey within five minutes
of sign-in; older sessions must sign in again. Each credential binds to the
same opaque owner. There are no passwords, TOTP seeds or remote resets.

## Private operator setup

Use an independent environment with `requirements-security.lock` and the editable
project package. Do not install into the running accepted environment. Create an
owner-only directory (`0700`) outside every checkout. All files below use `0600`.

For isolated tests, prepare a launcher configuration using the existing
`onejournal.local-web.v1` schema, pointing at a disposable fully migrated
journal, with unused ports and no real broker/report authorization. `start_page`
remains a canonical `/local/` page. This command does not create or repair a
financial journal. Existing-release owner operation requires explicit
`--owner-local` and the bounded switchover approval, not a prototype test result.

Prepare an HTTPS certificate for the DNS name `localhost` with a matching
private key. Tests may explicitly trust the certificate in their own client.
No TLS verification bypass, global trust installation, `127.0.0.1` RP ID, HTTP
cookie exception or implicit certificate generation is supported. Device/browser
trust is a later owner-controlled operating step.

From the prototype checkout, using that separate Python environment:

```text
python scripts/web/run_mac_passkey_prototype.py provision --web-config PRIVATE_CONFIG --security-db PRIVATE_SECURITY_DB --enrollment-file NEW_PRIVATE_ENROLLMENT_FILE
python scripts/web/run_mac_passkey_prototype.py serve --web-config PRIVATE_CONFIG --security-db PRIVATE_SECURITY_DB --tls-cert PRIVATE_LOCALHOST_CERT --tls-key PRIVATE_LOCALHOST_KEY
```

The uppercase arguments are placeholders for private existing/new file paths,
not literal paths to run. Provisioning does not start services or change the
journal. Existing security/enrollment files are never overwritten. The command
reports readiness only after a certificate-verified HTTPS page check. It binds
both services to loopback, preserves Host for the same-origin API proxy, refuses
occupied ports and stops only its owned process groups on Ctrl-C or child failure.

In a trusted supported browser, open the printed `https://localhost:PORT/local/...`
address. Read the enrollment file privately, enter its value in the enrollment
field, register a passkey with device verification, then sign in. Never put the
value in a URL, shell argument or chat. Use an independent second passkey when
available, or the approved offline/USB recovery method for this Mac-only scope.
Delete the consumed/expired
enrollment file when no longer needed; it cannot be used after registration.

## Controlled recovery and rollback

Stop the prototype first. Run the same operator script with `recover`, the same
config/security DB and a **new** enrollment-file path. Confirm `REPLACE PASSKEYS`
privately in the terminal. Recovery validates the existing journal/origin binding,
revokes every old passkey, preserves audit, and issues one new ten-minute grant.
Restart and enroll again. It cannot run through a website request, reset a
different binding or reset another process's active write-locked store. Recovery
requires local OS-owner authority; it is not safe against a compromised Mac.

Backups of an active security store or restoration of older keys/counters are
not an approved procedure. If state is lost, stop and provision fresh state with
explicit owner authority; never silently restore revoked access.

### Owner-approved USB access-setup recovery

On 2026-10-05, the owner selected an encrypted recovery backup on an ordinary
USB storage drive instead of requiring an independent second passkey for the
bounded Mac-first setup. A USB storage drive is not a FIDO2 authenticator. This
decision does not weaken WebAuthn verification, add an online reset or make the
USB a login factor. Existing offline recovery still requires local OS-owner
authority and a stopped service, and revokes all previous registrations.

`scripts/web/backup_mac_passkey_access.py` creates an AES-256 encrypted,
read-only compressed macOS disk image using the built-in `hdiutil` tool. It
copies an exact allowlist: the private launcher configuration, local PEM/DER
certificate, matching TLS key, recovery instructions and a hash manifest.
Never copy the directory recursively: security databases, old key counters,
session state, enrollment grants, financial databases and broker credentials
are excluded. The referenced exact financial-release files and journal need
their own backups; this access image is not financial/disaster recovery.

The owner chooses and confirms a unique 20-plus-character image password in
their own Terminal. The command sends it to `hdiutil` through private stdin,
never command-line arguments, environment variables, logs, Git or a password
file. Keep that password independently of the USB and a Mac-only copy. Losing
it makes the image unusable. No new dependency, drive formatting, existing-file
overwrite, trust-store change, journal write or service restart is performed.

```text
python scripts/web/backup_mac_passkey_access.py create --destination NEW_USB_IMAGE.dmg
python scripts/web/backup_mac_passkey_access.py verify --destination EXISTING_USB_IMAGE.dmg
```

These uppercase image paths are placeholders. Default source is the private
`~/.onejournal/passkey-access` setup; `--source-dir` can select a different
owner-private setup outside Git. Creation requires an already-mounted volume
under `/Volumes`, preventing a disconnected USB from being replaced by a local
folder. It refuses existing destinations. Plaintext staging/restoration uses
temporary owner-only local directories, not USB. It verifies encryption, image
checksums, read-only unlock, and temporary restoration with exact file hashes
before and after publishing the USB copy. It detaches only its own image mount,
not the USB, and removes its own incomplete output if publication fails.

For lost passkey access with intact local setup, use the existing offline
`recover` flow above. For lost setup, unlock the image and restore its four
setup files into a **new** owner-private local directory, with directory 0700
and files 0600. Validate the referenced financial files, certificate validity
and SSL trust. With explicit owner authority and services stopped, provision
a fresh security database and enroll again. Never restore an old security DB
or revoked access; no recovery step silently overwrites live state. The image
contains the same instructions. Refresh it after setup/certificate changes.

Password entry, creation and verification of the real USB image, owner passkey
enrollment and protected runtime acceptance remain operating steps, not claims
made by code presence or synthetic tests. Production encrypted journal backup,
key custody, audit restoration and full disaster recovery remain open work.

The helper creates a small blank local working image, populates only its own
temporary mount, detaches it and converts it to the encrypted read-only image.
This native sequence was rehearsed on the Mac: populated `-srcfolder` creation
returned `Resource busy`, independently of encryption or HFS+/APFS choice;
blank-image creation and populated-image conversion succeeded. No broader Mac
setting was changed to work around the tool failure. It follows Apple's
[encrypted disk-image workflow](https://support.apple.com/guide/disk-utility/create-a-disk-image-dskutl11888/mac)
and the installed `hdiutil` manual's stdin-password and conversion contracts.

### Bounded owner-local switchover

The owner approved one coherent Mac-only HTTPS/enrollment/recovery/runtime
package after the disposable prototype demonstration. The encrypted USB method
subsequently replaces the independent backup-passkey prerequisite for this
scope. The owner-created real USB image reported successful unlock and
disposable restoration on 2026-10-05; a read-only check confirmed an encrypted
image exists on that mounted USB. The owner privately controls its password.

Preflight requires the private owner config to match the accepted legacy config
byte-for-byte, the same journal/portfolio/report release authority and ports,
matching trusted localhost TLS, the isolated locked environment, unchanged
financial database and new owner-private security/enrollment outputs. Default
prototype mode refuses release-authorized configs before any provisioning.
Use `--owner-local` explicitly for provision, serve and recovery of this
approved owner setup. The supervised API child inherits that mode; its access
gate is never omitted. Neither this flag nor a passing check authorizes public,
LAN, tunnel, hosted/VPS, broker/provider, trading, database migration or Git work.

Provision only separate login state and a fresh ten-minute enrollment file.
Stop the exact verified legacy supervisor, letting it stop its own API/frontend,
before starting the protected pair on the same loopback ports. Confirm the HTTPS
page and anonymous route/export denial, with no financial DB change and no
unauthenticated duplicate listener. Then the owner privately enters the grant,
creates a passkey using their own device and signs in. TLS/device ceremonies
must never be completed by the agent or by bypassing a browser warning.

Rollback after a failed startup: stop only the new protected supervisor and
its managed children, then deliberately restart the unchanged canonical legacy
launcher with its original private config/environment. This restores only the
previous explicitly Mac-loopback-only operation, not a protected-security claim.
No financial restoration is needed because the switch does not write the journal.
If protected startup succeeds, keep it locked pending enrollment rather than
run an unauthenticated duplicate for convenience. Security state/unused grants
are retained privately; no silent credential reset or deletion is allowed.

## Verification and limitations

`tests/test_mac_passkey_access.py` uses real generated ES256 keys and CBOR
WebAuthn responses, not mocked successful verification. It covers deny-before-
reader behavior, exact origin/Host, user verification, owner binding, embedding,
signature, challenge replay/expiry, consumed enrollment, duplicate/limit checks,
CSRF, cookie flags, idle/absolute expiry, offline writer-lock recovery, permissions
and no journal change. CI installs the security lock so these tests do not skip.
The frontend access/report tests check request handling and unchanged decimal/
CSV contracts. Existing private API tests remain financial regression evidence.

Synthetic ceremonies and TLS clients do not prove Touch ID/iCloud Keychain,
independent backup-device enrollment, trusted real-browser authentication or
production acceptance. Those require the owner/device operating checkpoint.
P1-09 remains in progress, and Phase 1 remains 8/12 accepted; P1-10 through P1-12
are not completed by this implementation. Production RP ID, host/TLS, database,
monitoring, encrypted backups and end-to-end acceptance remain unresolved.

### Local validation receipt: 2026-10-05

In the isolated Python 3.13 environment: 10 passkey/security tests and 22 existing
private journal/portfolio API regressions passed; four route-contract tests
passed. Eight frontend access/report tests, TypeScript checks, focused lint,
dependency consistency and the tracked repository guard passed. The separate
HTTPS smoke verified four gated canonical pages, frame protection, explicit
certificate trust, anonymous denial without journal change, real signed synthetic
enrollment/login, authenticated existing API access and logout denial.

A read-only synthetic visual fixture showed the login/enrollment screen at
1280x720, 768x1024 and 390x844. Tablet/mobile had no horizontal overflow. It
accepted no credential actions and was not a TLS/device acceptance test; its
development HMR socket was intentionally not proxied. No browser warning was
bypassed and no trust store was changed. Temporary test services were stopped.
The accepted canonical site/API processes and checkout stayed unchanged.

The existing Starlette/httpx deprecation warning remains; it did not fail these
checks and was not used to justify unrelated dependency changes. No full-suite
local rerun, hosted build, public CI run, owner-device acceptance or Git
publication is claimed by this receipt.

### USB recovery preparation receipt: 2026-10-05

Five focused checks passed, including native AES-256 image creation, explicit
encryption detection, image checksum verification, read-only decryption,
byte-exact disposable restoration, wrong-password rejection, setup-file
allowlisting, no overwrite, missing-volume/symlink rejection and password
redaction. Only synthetic TLS/config files and temporary local images were
used. A read-only check of the actual setup confirmed the matching certificate
files/key and the mounted, unused USB destination; no source contents were
logged. The owner subsequently ran the command privately and supplied its
successful USB unlock/disposable-restoration receipt. A read-only Mac check
confirmed the encrypted image exists. No journal or Git publication change is
claimed; bounded runtime enrollment/acceptance is not proven by this backup.

### Owner-local runtime pre-enrollment receipt: 2026-10-05

The bounded protected site/API was started from the security worktree in the
isolated locked environment with explicit owner-local mode. The exact verified
legacy supervisor and its two managed children were stopped first. Only the
new pair listens on loopback ports 4173/8765; no legacy unauthenticated duplicate
was left running. The unchanged canonical launcher remains available for the
documented failed-startup rollback; it was not edited or synchronized.

The Mac's normal HTTPS client verified the localhost certificate and received
HTTP 200 on `/local/reports`. Anonymous journal, portfolio, report CSV and direct
API documentation requests received 401. Session status required initial
enrollment and reported no authenticated session. Exact financial database and
private-config hash comparisons were unchanged across provisioning, startup
and those negative requests. Only separate login state, its new ten-minute
enrollment file and normal value-free security audits were written privately;
the agent did not read the enrollment secret or submit a credential ceremony.

Eleven focused synthetic passkey tests passed, including the new owner-mode
pre-provision guard. Git whitespace/privacy checks passed. No Git publication,
financial migration/write, broker/provider use, VPS/public activation or Phase 1
completion is claimed. At this pre-enrollment checkpoint, real owner enrollment,
sign-in, accepted views and sign-out confirmation remained pending; the subsequent
owner-confirmed result is recorded below.

### Owner-confirmed Mac login check: 2026-10-05

The first ten-minute grant expired before the owner attempted registration. Its
expiry was established from creation time and the implemented contract, not
guessed from the generic frontend error. At the owner's "Ready" instruction,
the exact protected supervisor was paused. Under the offline writer lock, zero
registered credentials and expired enrollment were verified before renewing
the grant. No existing credential was removed; the prior security audit was
preserved and the financial DB hash remained unchanged. The same protected
service pair resumed, still denying anonymous requests. No expiry policy,
signature verification or trust rule was weakened.

The owner supplied a real-browser registration-success screenshot and confirmed
that passkey sign-in opens Reports normally. After being asked to sign out,
confirm the private Reports view disappears, then sign in again, the owner
replied "Yes both works." This records successful owner verification of the
basic Mac-only enrollment/login/Reports/logout/re-login flow. The browser brand,
authenticator brand and private cookie contents were not independently inspected;
no agent credential ceremony or financial screenshot was used.

Final anonymous journal and report-export requests returned 401; the trusted
HTTPS page shell returned 200. Only the protected API/frontend pair remained on
127.0.0.1:8765 and 127.0.0.1:4173. Canonical Git remained clean; the security
package is still uncommitted in its implementation worktree. No restart, Git
publication or financial write was performed for this final check (normal
value-free security-denial audit remains part of the running application).

The basic owner-login check is complete. It does not accept all of WEB-W10,
P1-09 or Phase 1, establish hosted/VPS policy, prove full financial/security-audit
disaster recovery, or replace the remaining security/quality/final release
review. The encrypted USB access-setup recovery receipt remains valid for its
stated access-only scope; it is not a second passkey or journal backup.

### Owner-confirmed two-tab sign-out: 2026-10-06

After the local cross-tab lock fix was validated and the protected Mac site
restarted from canonical code, the owner was asked to sign out in one of two
external-browser Reports tabs and check the other. The owner reported that
"both signed out." This confirms the visible two-tab lock for that Mac-only
browser check; it does not establish other-browser coverage, full WEB-W10/P1-09
acceptance or hosted security readiness. This browser check was completed on
the Mac before Git publication; it is not a hosted release check.

### Separate audit-history recovery image: 2026-10-06

The later owner-created USB image in `docs/mac_evidence_audit_recovery.md`
preserves the value-free security events that existed at capture time, alongside
the journal-linked private raw evidence. It deliberately does **not** restore
the security database, old passkeys, counters, sessions or enrollment grants.
Fresh offline enrollment remains the lost-access path. This bounded Mac
point-in-time backup does not complete WEB-W10/P1-09 or hosted recovery.
