# ADR-0031: Direct-to-passkeys Mac owner-access prototype

- Status: Accepted for local implementation and subsequently approved bounded Mac activation; basic owner-login check verified, full security/production acceptance pending
- Date: 2026-10-05
- Decision owner: OneJournal project owner
- Related work: P1-09, WEB-W10
- Supersedes: ADR-0030's deferred authentication direction and password/TOTP proposal, for this bounded prototype only
- Contract: `docs/mac_passkey_access_contract.md`

## Context and owner decision

After reconsidering password-only testing and a password/TOTP intermediate
step, the owner asked whether going directly to passkeys would be simpler,
then instructed: "Proceed with recommendations." This approves the complete
Mac-only prototype, its isolated dependency environment, disposable tests and
documentation. It does not approve production policy or operational activation.

Use verified passkeys with device/user verification, protected sessions and
controlled offline recovery. Do not implement password, TOTP, SMS, email,
security-question or remote reset fallbacks. This avoids maintaining a temporary
credential system that would later be replaced. Reuse the existing website and
private API routes; financial calculations and payloads stay unchanged.

## Decision and boundaries

- A single server-bound owner and journal, no public owner creation or tenancy.
- RP ID `localhost`, one exact HTTPS localhost port/origin. The production
  domain is unresolved. Production requires fresh enrollment against its own
  approved RP ID; localhost credentials are not assumed portable.
- Use the maintained `webauthn` library, constrained in the optional security
  extra and locked with its dependencies. Never implement custom verification.
- Require user presence/verification, challenge freshness and single use,
  signature, origin, RP ID, owner handle and counter validation. Reject embedded
  authentication. Zero-counter authenticators are supported by the library;
  nonzero counters must increase. Investigate counter rejection; do not weaken it.
- Store credential public keys, opaque owner binding, failures and value-free
  security audit in a separate owner-private security database, never financial
  tables. Sessions/challenges are volatile and revoked on process restart.
- Enrollment uses an expiring one-use secret written to a new private file by
  an offline operator command. It is not a reusable login password or recovery
  login bypass. Add independent backup credentials after recent sign-in when
  available; the subsequent Mac-first USB recovery decision is recorded below.
- Offline recovery requires stopping the prototype and an explicit terminal
  confirmation. It revokes every old credential and issues fresh enrollment.
  There is no unauthenticated reset endpoint. The security-store writer lock
  prevents another process resetting an active server.
- Secure, HttpOnly, host-only, SameSite=Strict cookies and session-bound CSRF
  protect private requests. Deny before invoking existing journal/report readers
  or writers. Never use an HTTP exception for secure cookies.

Prototype limits are 15-minute idle/8-hour absolute sessions, two-minute
challenges, ten-minute initial enrollment, five failed attempts per 15 minutes,
five credentials, and 32 pending challenges/sessions. These are conservative
implementation defaults, not OWASP mandates or accepted production service
budgets. Review them at owner-device acceptance rather than add a policy framework.

## Impact and consequences

Authority: offline owner provisioning plus the existing exact financial-release
authority. Producer: browser WebAuthn ceremony. Components: optional security
wrapper/store, HTTPS test launcher, shared frontend requests and login boundary.
Consumers: all private journal/trade, portfolio, report and CSV routes. Persisted
state: disposable security state only during this package. Financial impact:
none. Verification: signed synthetic ceremonies, negative routes, expiry/CSRF/
replay/recovery and same-origin HTTPS smoke. Rollback: stop the isolated prototype;
the accepted current launcher, environment, journal and runtime remain unchanged.

Passkeys remove password phishing but do not secure a compromised Mac, malicious
browser extension, stolen verified session, or unsafe recovery. Offline reset
relies on the local OS owner and filesystem boundary. There is no claim of
production readiness from this prototype.

Actual owner enrollment, trusted browser/device HTTPS acceptance, live journal
activation, system trust changes, Git publication, VPS/DNS, production migration,
broker/provider access and trading remain outside this implementation package.
P1-09 is in progress; P1-10 through P1-12 remain incomplete. ADR-0017's production
stack and ADR-0030's portability findings remain unchanged.

## Subsequent bounded Mac recovery decision: 2026-10-05

The owner approved an encrypted access-setup recovery image on ordinary USB
storage instead of requiring an independent backup passkey for this Mac-first
scope. Use built-in macOS AES-256 disk images with a password entered privately
by the owner and kept separately. Copy only launcher configuration, matching
localhost TLS certificate/key and recovery instructions/manifest; exclude
financial databases, broker credentials, enrollment grants and security stores.
Test read-only decryption and disposable restoration before claiming the real
USB backup valid. No drive erase or formatting is needed.

This backs up setup, not the authenticator's passkey private key. It does not
add password login, an unauthenticated reset or a remote recovery service.
Offline recovery remains OS-owner-controlled, revokes old registrations and
requires fresh passkey enrollment. A lost Mac additionally requires separately
backed-up journal and exact release files. Full financial/security-audit disaster
recovery and production policy are not accepted by this access-only decision.
The owner also manually configured SSL-only trust for the existing localhost
certificate; the Mac's SSL verification succeeded. The owner subsequently supplied
the real USB creation/unlock/restoration success receipt, and a read-only check
confirmed that the USB image is encrypted.

The subsequent owner-approved coherent switchover is limited to the existing
Mac-loopback journal and exact release authority: use its byte-identical private
config, provision separate login state, stop the verified legacy supervisor,
start its protected replacement and let the owner enroll/sign in privately.
The script requires explicit `--owner-local` for release-authorized operation;
the default remains isolated prototype use. `docs/mac_passkey_access_contract.md`
defines preflight, anonymous denial, unchanged-journal proof and rollback to the
unchanged canonical launcher if startup fails. This approval is not operational
acceptance, Git publication, a financial write/migration, production/VPS policy,
broker access or trading authority.

The owner subsequently supplied a real-browser registration-success screenshot,
confirmed that sign-in opens Reports, and confirmed that sign-out hides the
private view and signing in again works. Record this as a completed basic
Mac-only owner-login check, not full security/production or Phase 1 acceptance.
Final anonymous journal/export requests still returned 401, and the services
remained loopback-only. The contract records the just-in-time renewal of the
expired unused grant without removing any registered credential or weakening
expiry/verification. Device brand and private sessions were not inspected.

## Alternatives

Password-only is cheap initially but creates a phishing-prone intermediate
system. Password/TOTP adds credential/factor/recovery handling without phishing
resistance. External identity adds an unselected dependency and vendor/recovery
boundary. Direct passkeys are selected for the bounded owner flow, with the
explicit cost of trusted HTTPS/device enrollment and production re-enrollment.

## Sources

Implementation follows the [OWASP passkey guidance](https://cheatsheetseries.owasp.org/cheatsheets/Passkey_Security_Cheat_Sheet.html),
[WebAuthn RP ID rules](https://www.w3.org/TR/webauthn-3/#rp-id), and
[maintained library verification documentation](https://duo-labs.github.io/py_webauthn/authentication.html).
Installed library signatures/source were inspected; documentation version alone
was not assumed to match the locked runtime.
