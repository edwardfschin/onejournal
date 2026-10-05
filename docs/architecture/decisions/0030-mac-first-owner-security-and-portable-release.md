# ADR-0030: Prepare owner security on the Mac before a portable private release

- Status: Proposed
- Date: 2026-10-05
- Decision owners: OneJournal project owner
- Related roadmap items: P1-09, P1-10, WEB-W10, WEB-W12, OPS-06
- Related contracts: ADR-0017, ADR-0018, `docs/local_owner_journal_api_contract.md`, `docs/production_web_delivery_contract.md`
- Supersedes: None; does not change the accepted production foundation
- Superseded by: None

## Owner direction: local security implementation deferred

On 2026-10-05, after considering password/TOTP and passkeys, the owner chose
to keep the current Mac-only setup simple and defer additional website
security until VPS preparation. Neither login option is selected or approved
for implementation. The design below is retained as a deferred proposal,
not accepted policy or an active work package.

Keep the existing accepted private local-owner scope and loopback bindings.
Do not expose it to a LAN, public interface, tunnel, or forwarded port under
this direction. Preserve existing private permissions, exact financial-release
authorizations, privacy controls, and backups. No runtime, dependency,
credential, or database change is authorized by this deferral.

P1-09/P1-10 remain incomplete. Owner authentication, authorization, sessions,
recovery, HTTPS, and required operational controls must be approved and
validated before any private non-local staging or VPS exposure, not added
after soft launch. Portable compatibility review may proceed locally without
choosing a production host or silently changing ADR-0017.

## Context

The owner approved Mac-first preparation and deferring VPS deployment until
soft-launch readiness. This is not approval of an unspecified authentication,
recovery, hosting, or backup policy. The choices below remain proposed.

The existing launcher binds FastAPI to `127.0.0.1`. It selects the private
DuckDB and exact financial-release authorizations at process start. Its journal
reads/writes, portfolio, report, and CSV routes have no request-level owner
authentication or session checks. Journal operation UUIDs prevent conflicting
replays; they are not authentication or CSRF protection. The web development
proxy forwards both private API families. Settings is a synthetic preview,
not a working security administration page.

ADR-0017 accepts a portable React/TypeScript/Vite frontend, FastAPI authority,
and separately approved hosted PostgreSQL. The actual preview uses Vinext,
Next-compatible imports, Sites/Cloudflare plugins, Wrangler startup, and
Recharts. The bounded portability probe below proves that the existing build
can serve pages under Node, not that this server-rendered preview satisfies the
approved static-frontend topology. Mac acceptance does not silently accept
these differences for VPS production.

### Bounded portability evidence: 2026-10-05

The existing build was started on an isolated `127.0.0.1:4187` Node server
through the installed Vinext production-server API, with an empty inherited
environment and no dotenv loading, private API connection, or rebuild.
All seven demo and four local page shells returned HTTP 200; all 26 referenced
script/style assets returned HTTP 200. `/portfolio/local` returned HTTP 307
to `/local/portfolio`. The private portfolio API returned HTTP 404, proving
that this production server did not inherit the development-only API proxy.
The temporary server was stopped after this single smoke check. The accepted
site/API and database were untouched.

The current `start` script still invokes Wrangler, although the tested build
can run under Node without starting Wrangler for this probe. A packaged release
needs an explicit start configuration and same-origin private API routing.
These findings do not justify a framework rewrite merely to prove portability.
No browser hydration, private-data functionality, standalone dependency
packaging, Linux/VPS compatibility, or security acceptance is claimed by this
bounded page/asset check.

### Mac-local startup handover: 2026-10-05

Local commits `1f68f14` and `60eb9bc` deliver `bin/onejournal-web`, a foreground
launcher for the existing loopback API and development website. The canonical
Mac checkout now uses this launcher on ports 4173/8765 with the same previously
approved journal and exact release authorizations. Private setup lives outside
Git in an owner-only subfolder; existing folder permissions are unchanged.
The canonical Reports URL remains `/local/reports`.

Focused configuration, occupied-port, shutdown, and immediate-restart tests
passed. One real disposable-database smoke proved website/API proxy connectivity
and Ctrl-C cleanup. The actual handover passed read-only setup, page/asset,
API-schema, and proxy checks without requesting financial endpoints or changing
journal data. The launcher never takes over an existing listener; recently
closed TCP sockets are not mistaken for active services. See
`docs/operator_quickstart.md` for startup, shutdown, and rollback.

This is local operating convenience, not production packaging, authentication,
hosting, security acceptance, or completion of P1-09 through P1-12. The deferred
security proposal below remains unapproved and unimplemented.

## Decision

### Recommended local owner-security design

1. One explicitly provisioned owner, no public registration, invitations,
   additional roles, or broker credentials. Ownership is bound server-side to
   the selected journal/account scope; URL mode and client-supplied identities
   never establish authority.
2. Password plus an authenticator-app TOTP code for every new full session.
   Propose 15–128-character passwords, permit password-manager paste, and
   reject a local common-password list without an external password lookup.
   Use Argon2id through `argon2-cffi`, not custom password cryptography. Select
   explicit parameters no weaker than current OWASP guidance and measure one
   hash/verify on supported hardware. Use `pyotp` for TOTP and atomically reject
   a previously consumed time step. No full session after password alone.
3. Provisioning is an explicit private operator action, never first-visitor
   registration. Credentials, TOTP enrollment, and recovery material are entered
   privately, not pasted into chat, shell arguments, logs, or committed fixtures.
   Encrypt TOTP seeds using authenticated encryption through `cryptography`;
   keep the encryption key outside the database and source tree. Missing keys
   or unsafe private permissions block startup. No provider-connector Keychain
   item or broker secret is reused.
4. Server-managed, opaque random sessions. Store session-token hashes, not
   browser bearer tokens in local storage or financial data inside cookies.
   Bind sessions to owner and environment; rotate on authentication and
   reauthentication; revoke on logout, credential changes, and recovery.
   Proposed limits are 15 minutes idle and eight hours absolute, checked
   server-side. Explain expiry in the UI without leaving private cached views.
5. HTTPS session cookie: `Secure`, `HttpOnly`, `SameSite=Strict`, host-only,
   `Path=/`, with a `__Host-` name. One configured web/API origin; deny unexpected
   Host/Origin values, untrusted proxy headers, and wildcard credentialed CORS.
   Protect login, logout, recovery, and journal/security writes with verified
   origin and session-bound CSRF tokens. Preserve existing operation UUIDs.
6. Require owner authorization before every private route/service/resource
   access, including direct API calls, journal prose, CSV exports, and legacy
   route aliases. Financial result authorization remains an additional gate.
   A valid login never grants calculation, migration, provider, or order access.
   Protect or disable private OpenAPI/docs; responses are not privately cached.
7. Give generic authentication errors. Propose a five-failure/15-minute bounded
   attempt budget per configured owner and trusted client source, covering
   password, OTP, and recovery challenges. Persist throttling and revocation
   so process restart is not a bypass; do not add indefinite account lockouts.
8. Generate ten high-entropy, single-use recovery codes and store hashes only.
   Password plus one unused code can replace a lost authenticator; consumption
   is atomic and produces a restricted recovery session, not immediate report
   access. Require confirmed new MFA enrollment before a new full session.
   Password/factor changes require authentication within the last five minutes.
   If the password or all factors are lost, stop at an explicitly authorized
   offline owner-admin reset, revoke sessions, and reprovision. No email/SMS,
   security questions, recovery GET side effects, or unauthenticated reset API.
9. Record value-free authentication, denial, logout, factor-change, recovery,
   and revocation events. Never log passwords, codes, seeds, cookie/CSRF tokens,
   enrollment QR data, journal prose, holdings, or financial values.

These numeric limits are proposed project choices, not claims that OWASP
mandates these exact values. Versions and transitive dependencies must be
declared, constrained, reviewed, and validated before use; none were installed
to prepare this proposal.

### Mac-first delivery, then VPS

- Build and test the security service and login/logout/recovery UI in the same
  OneJournal workspace, using synthetic fixtures and disposable DuckDB copies.
  Prepare versioned security-state migration/rehearsal without touching the
  live journal. Preserve the accepted design, route registry, financial
  fingerprints, decimal contracts, and append-only journal behavior.
- Keep the accepted running site unchanged. An authenticated entry point must
  default-deny if security configuration is missing, rather than silently
  reverting to the legacy local-owner behavior. The legacy launcher is never
  a hosted deployment entry point.
- Test TLS with temporary certificates and explicit test-client trust, without
  installing a system trust root or claiming trusted real-browser acceptance.
  Trusted local HTTPS and activation against the private journal are a later
  explicit operating checkpoint, not an HTTP cookie-security exception.
- Inspect portable build/start output before choosing a VPS wrapper. Recommend
  aligning with ADR-0017 if hosting plugins are a necessary runtime dependency;
  preserve the existing UI and API rather than creating another website. Do
  not remove packages, migrate routing/charts, or accept Vinext as production
  architecture under this security prototype approval. Present the proven
  compatibility gap before any material framework change.
- Only after local security acceptance, resolve the exact VPS/domain/TLS,
  trusted proxy, production database migration, monitoring, encrypted backup
  and key custody, tested restoration, deployment, and rollback plan. Do not
  reuse development sessions/keys as production credentials. Do not rent a
  host, deploy, or transfer private data during this package.

## Boundaries

One subsequent approval can cover acceptance of this proposed owner-security
design plus its complete Mac-only implementation, the three named runtime
dependencies in an isolated test environment, disposable-copy migration and
security-state rehearsal, focused tests, synthetic UI checks, and documentation.
It excludes live journal writes, actual owner enrollment, accepted API/site
activation or restart, system certificate-trust changes, Git publication,
framework migration, VPS, DNS, external identity accounts, broker/provider
access, and trading. P1-09/P1-10 remain blocked, not complete from this proposal.

## Alternatives considered

| Option | Benefit | Cost or risk | Recommendation |
|---|---|---|---|
| Password + authenticator + offline codes | Works independently of an identity vendor or final VPS domain; familiar single-owner workflow | Password/TOTP can be phished; OneJournal must maintain credential, seed, recovery, and session controls | Recommended bounded Mac-first design; not described as phishing-resistant |
| Verified passkeys with independent recovery | Phishing-resistant authentication with user verification; no stored password/TOTP seed | Requires an approved relying-party origin, device enrollment and recovery plan; local-to-production enrollment is not automatically portable | Viable stronger alternative if the owner prefers it before implementation |
| External OIDC identity service | Delegates credential/MFA lifecycle to an identity system | Adds external identity configuration, connectivity, recovery dependencies, and vendor/self-hosted operations choices | Defer unless an existing owner-approved identity service is identified |
| Loopback or VPS access gateway alone | Little application work | Network reachability is not route/service/resource ownership or complete session/recovery protection | Not sufficient for the approved private production gate |

## Consequences

The recommended scope avoids a paid identity service, additional tenancy,
email infrastructure, another website, and speculative execution capability.
It retains responsibility for security review and ongoing dependency upkeep.
It protects against unauthenticated callers and cross-site requests, not a
compromised Mac/root account, malicious extensions, or all phishing.

## Compatibility and migration

Authentication adds intentional 401/403/429 failure semantics. Existing
frontend clients need shared authentication/expiry handling and CSRF support;
financial payload versions, accepted release authorization, and route identity
stay unchanged unless a demonstrated breaking change requires versioning.
Security state includes owner/credential binding, encrypted MFA material,
recovery hashes, revocable sessions, throttling, and audit. Prototype it only
in disposable state; its live schema and PostgreSQL mapping need separately
approved migration and exact backup/reconciliation. Never store plaintext
credentials in journal financial records or manually reinterpret ownership.

## Security, privacy, and financial impact

| Impact | Source, producer, component, or consumer |
|---|---|
| Authority | Accepted ADR-0017/0018 and exact financial-release contracts; this ADR is only proposed |
| Upstream | Private operator enrollment plus browser authentication; no broker calls |
| Changed components | New security service/store and authenticated API entry point; local launcher/config contract; shared frontend client, login and recovery views |
| Downstream | All private journal, portfolio, report/CSV routes and their frontend consumers |
| Persisted state | New security state and audit in disposable copies only during implementation |
| Financial impact | No recalculation, changed financial data, new acceptance, or provider/order authority |
| Validation | Deny unauthorized route/service/resource and export access; prove session, CSRF, replay, recovery, throttling, privacy, and fixture UI behavior |
| Rollback | Leave accepted runtime untouched; discard disposable security state; revert only this package's local edits |

## Validation

Use focused tests, not repeated whole-project runs after every small edit:

- anonymous/direct API and export access, wrong owner/account/resource,
  guessed identifiers, alternate routes, and missing security configuration
  fail before private reads or domain writes;
- password-only, invalid/expired/replayed OTP, reused/concurrent recovery,
  invalid origin/Host/proxy headers, absent/forged CSRF, and throttled requests
  deny access without secrets or private data;
- cookie attributes, fixation resistance, idle/absolute expiry, restart
  revocation behavior, logout, credential/factor changes, and recovery limits
  work with deterministic clocks and concurrent replay tests where necessary;
- accepted synthetic financial reads and append-only journal retries still
  match existing payloads and exact financial fingerprints;
- desktop/mobile keyboard-accessible fixture login/logout/recovery screens
  show actionable expiry/unavailable states without cached private values;
- encrypted security-backup restoration is exercised with disposable state
  and separately supplied keys; no stale sessions or consumed recovery codes
  regain authority after restore;
- run changed-component tests, type/lint/build, documentation/privacy checks,
  and one relevant regression pass before handoff. Real private activation,
  trusted browser verification, PostgreSQL migration, and hosted acceptance
  are not claimed from fixture tests.

## Rollback or supersession

Until approval this ADR changes no policy or runtime. Before activation, revert
only the focused prototype and preserve the existing owner-accepted release.
After activation, security rollback must fail closed or stop private serving;
it must never expose an unauthenticated service as a convenience fallback.
Preserve journal history and security audit. Later identity, recovery, or
hosting policy changes require a superseding decision with compatibility and
recovery evidence.

## Primary guidance checked on 2026-10-05

- [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html): Argon2id and explicit work-factor selection.
- [OWASP MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html): TOTP trade-offs, verified passkeys, and factor/recovery risks.
- [OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): server-side session lifecycle and protected cookies.
- [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html): tokens and origin controls; SameSite is not a universal substitute.
- [argon2-cffi API](https://argon2-cffi.readthedocs.io/en/stable/api.html) and [PyOTP](https://pyauth.github.io/pyotp/): library interfaces, parameter maintenance, seed confidentiality, and consumed-code rejection.
