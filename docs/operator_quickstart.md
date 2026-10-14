# OneJournal Operator Quickstart

## Purpose

This covers the current private local website and the legacy internal prototype.

OneJournal is read-only toward brokers. Private journal entries and reviews can
be saved through their approved application boundaries. It does not place,
cancel, replace, or modify broker orders or auto-trade.

## Current protected Mac website

The owner-approved site uses trusted `https://localhost:4173` and passkey login.
The current 2026-10-12 public wheel/static release is built from `c173b88`
and installed in a separate permanent environment. One Python process serves
the static website and protected API together on loopback HTTPS; no Node
runtime or listener on port 8765 is needed. The approved maintenance publication
advanced the existing journal to 0028 and selected new exact authorizations.
Saved passkeys, certificate and security policy are unchanged.

To start the installed release after stopping its own existing terminal, set
`OJ_WEB_CONFIG` to the active private configuration recorded in the private
publication receipts. Do not silently use the earlier authorization config:

```bash
OJ_RELEASE="$HOME/.onejournal/releases/mac-static-20261012-quality"
OJ_ACCESS="$HOME/.onejournal/passkey-access"
test -n "${OJ_WEB_CONFIG:?Set the active private configuration path first}"
"$OJ_RELEASE/python-env/bin/onejournal-mac-site" --owner-local \
  --web-config "$OJ_WEB_CONFIG" \
  --security-db "$OJ_ACCESS/access.duckdb" \
  --tls-cert "$OJ_ACCESS/localhost-cert.pem" \
  --tls-key "$OJ_ACCESS/localhost-key.pem" \
  --static-dir "$OJ_RELEASE/onejournal-mac-release/static"
```

Keep that terminal open; Ctrl-C stops this process only. Existing listeners
block startup; recently closed TCP connections do not. Restart clears browser
sessions, not saved passkeys. Sign in again in the external browser that holds
your passkey. No migration, data refresh, provisioning or recovery occurs.
Do not start the legacy launcher below to bypass a login problem.

For daily Mac startup, an owner-private `StartOneJournal.command` shortcut is
available under `~/.onejournal/launchers`. Double-click it in Finder when the
site is stopped, then keep its Terminal open. It invokes the same installed
foreground command with the current exact configuration; it does not install
software, select a newer release, migrate, recover, contact a broker or run at
Mac login. The underlying command still refuses an occupied port. Leave an
already running service alone rather than starting a duplicate.
The shortcut contains machine-private file locations and stays outside Git.
After a deliberate future release/configuration switch, update it explicitly;
do not fall back to an older authorization file.

Financial rollback is deliberate, not an automatic latest-release switch.
Stop only the owned service, then select the retained previous private
configuration with the current installed runtime, which carries the SQL
resources required by the migrated journal. An old report selection does not
itself roll back trade history; that requires the explicitly recorded prior
history revision. Do not delete appended evidence or reviews. Full restoration
requires a separate deliberate recovery while quiescent, preserving subsequent
owner work. The verified pre-migration and pre-report backups and their exact
scope are recorded privately. No rollback occurs during normal startup.
The earlier `19b0bd8` installed environment lacks the new checksum resources
and must not be used against the migrated journal.

UI-only rollback uses the retained `mac-static-20261011-refresh` environment
and its matching static directory with the **same current** private configuration,
security store and TLS files. Stop only the owned current process first; do not
restore a database or select old financial authorizations. The previous private
shortcut is retained with the private handover receipt. The new shortcut selects
`mac-static-20261012-quality` explicitly; there is no automatic rollback.

The canonical checkout at `cc1fa8a`, prior environments and original private
configuration remain unchanged. Do not run two versions together or bypass
passkey protection. The owner verified the earlier installed-release handover
and confirmed sign-in and the site after the current UI-only restart. This is
bounded Mac operation, not Phase 1 completion. See
`docs/mac_passkey_access_contract.md`.

### Read-only release and connection check

On 2026-10-13, the owner authorized starting the same installed `c173b88`
release through its unchanged private shortcut. The pinned public artifact,
owned loopback listener, verified HTTPS shell and anonymous enrolled access
status passed the check below. No installation, migration, financial API request,
broker call or passkey ceremony was performed. Keep that Terminal open and
sign in with the existing passkey when needed; restart clears sessions, not
enrollment. This is bounded transport verification, not fresh financial/login
acceptance. The previous connection refusal remains recorded separately.

The owner accepted the combined Mac-testing profile on 2026-10-13; see
`production_web_delivery_contract.md` for its exact scope and measured browser
evidence. It adopts manual operating choices, not a scheduler or production SLA:

- Create a new encrypted journal/release image after a day with journal edits
  and after an approved financial publication, selecting the active config.
- Refresh evidence/audit after new accepted source lineage and weekly during
  active use. Refresh access/TLS only when that setup changes. Use the existing
  quiet/stopped-source procedures; unchanged journal days need no new image.
- Keep current trial images/evidence/revisions/audit, with passwords separate
  from USB. No automatic deletion, old-passkey restore or external alert service.
- Use the foreground protected site when attended. Check after release changes
  or startup/error concerns, not continuously. Keep Streamlit parked, never as
  an unprotected fallback. Ordinary outages are investigated on next use.

The loss targets depend on performing these backups: at most one working day
of journal edits and up to a week of security-audit lag. On 2026-10-13 the existing
images passed the complete same-Mac restored-service signed-client check within
the one-working-day trial target, including private password entry. This is not
another-Mac/host recovery or owner-hardware re-enrollment proof. The owner also
confirmed clear VoiceOver headings/controls/table and prompt Reports opening,
then accepted closing the bounded Mac-testing work. The successful receipt and
exact release acceptance remain private. Existing evidence is reused; no repeat
backup, browser suite or further routine approval is needed. History and hosted
soft-launch work remain separate; formal Phase 1 stays 8/12.

Use the locked security Python environment and the reviewed source checkout:

```text
python scripts/web/check_mac_release.py --release-dir ABSOLUTE_PUBLIC_RELEASE --manifest-sha256 PINNED_MANIFEST_SHA256 --source-commit PINNED_SOURCE_COMMIT --site-origin https://localhost:4173
```

Uppercase values are placeholders, not literal arguments. Obtain both pins from
the separately retained verified release receipt/original artifact, not by
hashing an untrusted directory and treating that as proof. Preserve the pins
independently when packaging or accepting a release. A checksum is not a publisher
signature. The release directory is the public `onejournal-mac-release` folder,
not its enclosing Python environment or any private-data directory.

The check verifies the existing v1 manifest, exact source commit, every file
checksum, complete inventory and static-route contract. Links, extra/missing
files or mismatches fail with a nonzero exit and a value-free error. It never
extracts an archive, installs packages or repairs files. Omit `--site-origin`
for file-only validation. The optional connection check makes only two
cookie-free GETs: the exact Reports shell and existing anonymous access-status
endpoint. It requires verified HTTPS, matching public shell bytes,
privacy/frame headers and already-enrolled anonymous access status. There are
no redirects, proxy settings, retries, TLS exceptions or authenticated/financial
requests. Source inspection and a disposable integration check establish that
the status endpoint creates no ceremony/session or audit event in this flow.

Python's default TLS store is not assumed to import Mac Keychain trust. If the
approved localhost setup needs explicit certificate trust, also pass
`--tls-cert EXISTING_APPROVED_CERTIFICATE --tls-cert-sha256 PIN_FROM_SETUP_RECEIPT`.
Both options are required together and only with `--site-origin`; use the
certificate, never the private key. The exact original bytes must match the
separate setup/handover receipt before connecting. This reuses the established
localhost trust used by installed-release checks; it does not accept a replacement
certificate or install a trust root. Hostname, signature and validity verification
remain enabled. Never use an insecure-client exception to make the check pass.

Success means artifact integrity and, if requested, bounded transport/access
status only. It does not prove owner sign-in, financial freshness/reconciliation,
dependency security, recovery, browser accessibility or hosted acceptance.
It checks the public wheel/static files, not every installed Python module or
dependency; retain the separate installation/source and dependency receipts.
The command opens no journal/security database and changes no configuration,
credential, source file or runtime. It is an on-demand operator check, not an
automatically enabled monitor or hosted availability/alert guarantee.

### When a check fails

- **Connection refused:** the foreground service is not reachable at that origin.
  Check its existing Terminal first; start only the protected command above
  when deliberately authorized. Do not start a duplicate or legacy fallback.
- **TLS failure:** check the existing certificate's validity and intended SSL
  trust. Do not click through a warning, disable verification or regenerate
  trust material automatically. Certificate replacement needs its own exact
  setup/recovery update.
- **Artifact mismatch:** retain the files and original receipt, and investigate
  the exact changed/missing component. Do not re-hash altered files into a new
  accepted manifest, overwrite the environment or automatically roll back.
- **Login/access failure:** use the external browser holding the passkey.
  If access is genuinely lost, use the stopped-service offline recovery in
  `mac_passkey_access_contract.md`; never restore revoked credentials/counters.
- **Suspected private-data exposure or incorrect displayed figures:** stop only
  the owned protected foreground process, preserve private evidence/audit and
  investigate. Do not bypass authentication or patch database/generated values.
  Any recovery, publication or reactivation follows its existing exact authority.

These actions follow the accepted bounded Mac-testing profile, not a hosted
response-time or notification promise. Journal/release, access/TLS
setup, and evidence/audit recovery images have different scopes; use their
recorded exact manifests and restore into new private locations only. A later
live restoration must preserve work since the backup and requires explicit
authority. Do not repeat dated successful USB restoration merely to generate
another PASS.

### One-session disposable Mac recovery close-out

`scripts/web/rehearse_mac_recovery.py` uses the **existing** journal, access and
evidence/audit images. It asks for each password privately in the owner's Mac
Terminal; it creates no new image. Select the approved installed Python runtime
and public artifact with independently retained manifest/source/TLS pins.
Use a new receipt in an existing owner-private directory outside Git and a
separate free loopback port (default 4174; live port 4173 is refused).

The operator reuses the existing encrypted-image verification/restoration code,
keeps copies only for the scoped session, matches restored journal/evidence
lineage and writes a new config bound solely to restored journal/release paths.
It leaves original image/config files intact. A fresh **temporary** security
store and signed ephemeral test device exercise the installed protected service:
trusted HTTPS and exact shell, locked anonymous financial access, enrollment,
login, current account/symbol reports and matching CSV, then logout/lock. Only
three reporting-read audit additions are allowed in the disposable journal;
schema and other relation counts must remain unchanged. No history request,
migration, publication, owner-device credential or browser session is created.
It imports the existing test authenticator from the reviewed source checkout;
this is an operator rehearsal, not an installed standalone release command.

The new child is stopped before its temporary copies are removed, including on
failure. Original recovery images are hash-compared and preserved; the existing
live site, security store and journal are not opened or replaced. A new private
receipt remains `incomplete` on failure and records the exact runtime source and
elapsed session time only after success. Do not overwrite a prior receipt on a
retry. The owner-private convenience shortcut selects a fresh receipt per run;
the operator records fixed, value-free stages so an image unlock, lineage or
service failure can be distinguished without exposing exception bodies. Image
passwords are the passwords chosen when creating each encrypted USB image,
not the Mac login password, a passkey or a new password to choose for this check.
Passing this signed-client check is not owner-hardware re-enrollment,
another-Mac/host recovery, fresh financial acceptance or production clearance.

The hands-on Safari/VoiceOver check was owner-confirmed on 2026-10-13 and is
closed for the unchanged Mac-testing release. Do not repeat it simply to obtain
another PASS. For a later relevant change, use Safari on the **protected site**,
sign in with the existing passkey, and verify Reports opens promptly. Temporarily
turn on VoiceOver, listen to a heading, filter/action and table context, then
restore the prior setting. No private numbers or screenshots need to be sent
to chat. Report usable/not usable and any control that could not be read.
Combine that result with one dated exact-release owner acceptance; do not turn
each control or password prompt into another approval ceremony.

### Release export, corrections and closure limits

Reports CSV exports cover the same currently authorized financial selection;
they are not a full journal narrative, lifetime-history or disaster-recovery
export. Preserve the displayed selection, as-of and incomplete/unavailable
state when reviewing an export. Never publish private CSV files into Git.

Journal entries are corrected through their existing append-only revision
boundary; previous revisions remain evidence. Financial/import corrections
require source reconciliation and a separately reviewed exact result, not a
manual database edit or an assumed newest release. Historical evidence migration
0029 remains source/disposable-copy work and is not activated by this runbook.

No implemented general financial-history deletion, full-account closure or
retention-expiry command is claimed. Before such work, identify the selected
private files, recovery images, audit requirements and approved retention scope;
do not delete data or revoke credentials under a general closure request. Streamlit
remains the retained internal prototype, not the protected release or a login
fallback. The accepted trial preserves existing evidence; no destructive
retirement, automatic erasure or permanent production-retention rule is adopted.

### Reloading saved data versus fetching fresh broker data

On the protected website, open **Data** and choose **Reload saved data**.
It rereads the currently active accepted report from the local API, including
its saved snapshot date and history coverage. It does not download broker data,
refresh credentials, recalculate P&L from new evidence or publish a new release. Reloading
the browser likewise does not make an old snapshot current.

Website-triggered broker downloads are not activated; the prepared request/status
controls are disabled by default. Fresh evidence currently
uses the separately scoped operator capture, reconciliation, review and
publication workflow below. No new broker request or financial acceptance is
implied by clicking Reload saved data.

## Legacy local website launcher: one terminal

The repository's `bin/onejournal-web` launcher starts the legacy unauthenticated
loopback API and development website together,
opens the canonical local page, and keeps both in one foreground session.
It is not a production server, login implementation, VPS deployment command,
import, migration, or financial calculation.

After the normal Python and `web/` dependency setup, configure it once:

```bash
./bin/onejournal-web configure
```

Enter the **existing approved** journal database and optional portfolio/report
authorization file locations privately in that terminal. Input is hidden. Do
not paste credentials or private configuration into chat. Blank authorization
locations deliberately keep those financial routes unavailable. Configuration
is saved outside Git at `~/.onejournal/local-web/config.json`, mode `0600`, inside
a dedicated owner-only `0700` folder. Existing configuration is never overwritten;
the permissions of an existing `~/.onejournal` folder are left unchanged.

For normal use:

```bash
./bin/onejournal-web
```

Keep that terminal open. **Ctrl-C stops both services started by this command.**
If either service crashes, its managed companion stops too. The launcher never
kills an existing port owner or reads a stale PID file. If the previous two
manual terminals are still running, it refuses occupied ports; leave those
services alone until a deliberate switchover is approved.

`./bin/onejournal-web --check` validates dependencies, private permissions,
existing journal schema, and exact release authorizations without starting
services, migrating the database, or writing read-audit rows. It does not
require the normal ports to be free. `--no-browser` suppresses automatic browser
opening. `--config` selects another private configuration file outside Git.
`ONEJOURNAL_PYTHON` / `ONEJOURNAL_VENV_DIR` select the existing Python environment;
`ONEJOURNAL_NODE` can select an installed Node executable. Nothing is installed
automatically. Python 3.11–3.13 and Node 22.13+ are required.

The optional configuration fields are `broker_current_authorization`,
`reporting_authorization`, `web_port` (default 4173), `api_port` (default 8765),
and `start_page` (a canonical `/local/` Journal, Trades, Portfolio, or Reports
path). Required fields are `contract_version: onejournal.local-web.v1` and
`journal_db_path`. Ports must be different and unprivileged; a host or remote
API URL cannot be configured. The default page is Reports when report authority
is configured, otherwise Portfolio when portfolio authority is configured,
otherwise Journal. The website refuses to silently switch to another port.

The launcher reads the same accepted financial authority as the manual API
launcher. Startup validation does not update data. Once the browser loads,
existing privacy-safe read audits and explicitly submitted journal writes work
as before. Saved snapshots remain dated snapshots, not live quotes.

Rollback: stop this managed session and return to the previous two-terminal
procedure using the same existing private files. No journal schema, data,
release authorization, broker credentials, or accepted financial fingerprints
are changed by installing the launcher. The current launcher is still
unauthenticated and must remain loopback-only. The separate opt-in passkey
prototype in `docs/mac_passkey_access_contract.md` is for disposable local
testing by default. The separately approved bounded Mac switchover uses explicit
`--owner-local`, trusted HTTPS and private passkey enrollment; its activation and
rollback follow that contract, not this legacy command. Security is required before private
non-local exposure.

The owner-approved Mac access-setup USB recovery method is documented in
`docs/mac_passkey_access_contract.md`. Use its encrypted-image command from
your own Terminal; never enter the image password in chat. It is not a backup
of financial data or the Touch ID passkey, and does not activate the protected
site, erase the USB, restore old credentials or complete production recovery.

For the separate complete operational-journal/exact-release backup and
disposable restoration check, see `docs/mac_journal_recovery.md`. It preserves
the access image and does not overwrite live state or restart services. Creating
the lasting encrypted USB journal image requires the owner's private Terminal
password entry; a temporary rehearsal is not a lasting backup.

For the current backup refresh, explicitly select the active publication
configuration for both journal and evidence/audit commands. The latter now
includes validated snapshot evidence as well as legacy lineage. Use new image
destinations and retain the previous set. Stop only this site's own service
for the audit capture, then start the same protected installed release; no
passkey replacement or data restore is part of taking a backup.

The owner's 2026-10-12 receipts and independent encryption checks complete the
dated journal/evidence USB refresh. The extra wrapper byte-guard warning was
recorded separately rather than erasing it or repeating successful image tests;
see `docs/mac_evidence_audit_recovery.md`. Passwords remain private and previous
images are retained. This does not create a backup schedule or retention policy.

If the browser says the site cannot be reached, first distinguish a stopped
foreground service from a login problem. This installed Mac service does not
automatically start after closing its terminal or restarting the Mac. Start
the protected command above with the active config, keep its terminal open and
sign in with the existing passkey. Do not run a second server, the old
unauthenticated launcher, enrollment or database repair merely to reach the page.

The sections below retain the legacy Streamlit/import operator procedures;
they are not required merely to start the local website.

## Updating the data shown by the private website

Reloading Reports or changing a filter rereads the selected saved release.
It does not call Schwab, ingest files, recalculate P&L, select the newest
database release or advance the displayed as-of date. The report authority is
selected and validated when the API starts.

The safe evidence-to-display path is:

1. Obtain an explicit new private evidence bundle through the existing bounded
   Schwab bridge: complete positions, transaction/lifecycle history and the
   required quote/session lineage. ADR-0016 keeps OneBot as sole token owner;
   no shared credentials, website-triggered fetch or automatic polling.
2. Validate the immutable source and assemble/reconcile it through OneJournal's
   existing v2 evidence/history-revision path, using a disposable journal copy
   first. Preserve prior revisions, journal notes and reviews.
3. Reconcile a new broker-current valuation and bounded realized result, then
   prepare and rehearse a new exact immutable report release. A prior financial
   acceptance does not approve new values or a new fingerprint.
4. Only after the new result is accepted, take a fresh verified backup, append
   the approved data/release and deliberately switch the protected API's exact
   authorizations. Live writes and runtime activation are separate from local
   preparation; the old release remains rollback evidence.

The 2026-10-09 review found local v2 assemblies dated 2026-09-04, not a newer
assembled update. The first-release-only operator gap was then corrected
locally; that correction does not acquire data or refresh the running site.

The approved capture/rehearsal/publication close-out is recorded in
`docs/mac_data_refresh_capture_plan.md`. Exact financial scope and new
configuration/authorizations are retained only in private publication receipts.
The displayed state remains a saved snapshot, not continuous refresh. Existing
encrypted USB images are older dated backups and were not refreshed by this
publication. Another capture requires its own explicit scope; do not reuse
historical approvals.

For a subsequent release, both `prepare_phase1_reporting_release.py` and
`persist_phase1_reporting_release.py` require the additional
`--predecessor-report-authorization` option naming an existing private accepted
release authorization file. The predecessor is explicit, never automatically
selected as "latest." Preparation writes a v2 package binding that predecessor
and the existing report/audit state; persistence must use the same predecessor.
The update requires migration 0026 by default. A snapshot-history target already
at exact migration 0028 requires explicit `--expected-migration-version 0028`
on the persistence command; it never migrates the database implicitly. A version
mismatch or mismatched 0027/0028 schema ledger fails before a write, and the exact
version and snapshot contracts are rechecked at the write boundary. The audit
reports the selected, verified version. An unchanged account/alias scope and a
fresh report acceptance are still required. Changed financial fingerprints also require fresh financial
acceptance identities. Existing unchanged financial results can retain their
existing acceptance. Initial-release v1 packages remain supported without the
new option; unrelated existing releases still block that initial-release path.

The rehearsal proves append and identical replay on a new disposable copy,
preserves prior report/audit rows and leaves the source unchanged. A changed
report/audit baseline invalidates the prepared package, even if row counts are
unchanged. Persistence remains dry-run by default; `--persist` still requires
an exact database digest, a distinct byte-identical private backup and a
quiescent database. Do not remove guards, clear tables or invent an acceptance
identity. New source evidence, accepted results, live persistence and protected
API activation are still needed for an actual data update.

The legacy `refresh_dashboard.py`, `refresh_dashboard_db_transition.py` and
daily-import commands below are not substitutes for this website release path.
The transition script invokes `import_journal_to_db.py --replace`; do not run it
against the accepted private journal. CSV/dashboard generation does not update
the process-start report authority. See `docs/phase1_reporting_release_contract.md`
and `docs/schwab_history_materialization_revision_contract.md` for the financial
and append-only history boundaries.

## Activate OneJournal

Run from the repository root:

```bash
source bin/activate_onejournal.sh
```

This activates the canonical machine-local OneJournal Python environment and
moves into the project folder. A shell alias may wrap this command, but the
repository helper is the authoritative activation path.

## Baseline Check

Run: ./bin/onejournal_check.sh

Expected final line: PASS OneJournal baseline looks good.

If it fails, fix the failing section before continuing.

## Refresh Dashboard Payload

Run: python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write

This rebuilds the generated DB payload from DuckDB canonical episode and
current review-projection state.

## Edit Manual Reviews

After migration 0005, durable review history is DuckDB `journal_reviews` and
`manual_reviews` is the current compatibility projection.

Edit review_status, setup_quality, entry_reason, and notes.

Do not edit episode_uid unless the trade episode itself changes.

After saving reviews in Streamlit, the DB dashboard payload is rebuilt from the
current compatibility projection.

## Start Dashboard

Run: streamlit run src/onejournal/apps/streamlit_app.py

Then refresh the browser page.

## Current Data Source

Current prototype input: docs/examples/manual_csv/fills_template.csv

This is a sample manual CSV file used to test Sell Put, Buy Call, and vertical workflows.

## Multi-Leg Trade Grouping

Use episode_group_id to group related legs into one trade episode.

For single-leg trades, episode_group_id can be unique per trade.

For verticals or multi-leg trades, all related legs must share the same episode_group_id.

Example: SPY_PUT_VERTICAL_001

OneJournal currently supports simple 2-leg vertical classification and can safely group up to 4-leg option trades as Multi-Leg Option.

## Supported Strategy Labels

Current prototype validates these strategy labels:

- Sell Put
- Buy Call
- Sell Call
- Buy Put
- Put Credit Vertical
- Put Debit Vertical
- Call Credit Vertical
- Call Debit Vertical
- Stock Long
- Stock Short

3-4 leg option trades are grouped safely as Multi-Leg Option until a more specific classifier is added.

## Current Flow

manual CSV fill -> NormalizedFill -> strategy classification -> TradeEpisodePreview -> DuckDB journal history and current projection -> dashboard payload -> Streamlit dashboard

## Safety Rules

No broker API in this prototype.

No auto-trade.

No order placement.

No order cancellation.

No order replacement.

No broker credentials in CSV files.

## Normal Daily Prototype Loop

1. actoj

2. ./bin/onejournal_check.sh

3. python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write

4. Use Streamlit DB payload Save Review to append history and update the current projection.

5. Save Review in Streamlit atomically writes both review layers and rebuilds the DB dashboard payload.

6. streamlit run src/onejournal/apps/streamlit_app.py

7. Refresh Streamlit browser page.

## DuckDB Phase B Review Store

OneJournal uses DuckDB `journal_reviews` as durable history after migration
0005 and `manual_reviews` as the temporary editable compatibility projection.

Use this command when you want to refresh the dashboard and prove that the CSV-built payload and DB-built payload still match:

```bash
python scripts/journal/refresh_dashboard_db_transition.py
```

What it does:

1. Rebuilds the normal CSV dashboard payload.
2. Imports fills and legacy/backfill CSV reviews into DuckDB when a resync is needed.
3. Checks the DuckDB journal database.
4. Builds a dashboard payload from DuckDB.
5. Compares the legacy CSV-built payload against the DB payload for migration safety.
6. Runs the OneJournal baseline check.
7. Prints a final result block.

Expected final result:

```text
CSV_PAYLOAD_REFRESH=PASS
DB_IMPORT=PASS
DB_CHECK=PASS
DB_PAYLOAD_BUILD=PASS
CSV_VS_DB_PAYLOAD_COMPARE=PASS
BASELINE=PASS
OVERALL=PASS
```

Safety notes:

- This runner is read-only from a trading perspective.
- It does not call broker APIs.
- It does not place, cancel, or modify orders.
- It does not enable auto-trade.
- It keeps the existing Streamlit dashboard flow untouched.


## Phase B Review Save

Streamlit DB payload Save Review appends durable history and updates the compatibility projection.
CSV manual_reviews.csv is legacy/backfill/export only.
No auto-trade.

## Phase B Default Payload

DB payload is the default Streamlit payload in Phase B.
Save Review appends durable history and updates the compatibility projection.
CSV payload is legacy/backfill/export only.
No auto-trade.

## Phase B Read-only Payloads

CSV and Custom payloads are read-only in Phase B.
Use DB payload to save reviews.
CSV manual_reviews.csv is legacy/backfill/export only.
No auto-trade.

## Phase F Current Operator Runbook

Use this sequence for the normal OneJournal DB review workflow.

```text
1. Confirm Git identity and clean status.
2. Run ./bin/onejournal_check.sh.
3. Build the DB dashboard payload from DuckDB canonical state and the current review projection.
4. Run check_db_dashboard_contract.py to prove dashboard_payload_from_db.json has the expected DB schema.
5. Run check_save_review_flow.py to prove Save Review works end to end on a temporary DB copy.
6. Launch Streamlit.
7. Select DB payload.
8. Use Save Review to DuckDB.
9. Treat CSV and Custom payloads as read-only.
10. Confirm no broker API call, no order placement, no order cancellation, no order modification, and no auto-trade.
```

Normal DB payload build:

```text
python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write
```

DB payload contract check:

```text
python scripts/journal/check_db_dashboard_contract.py --asof 2026-06-02 --payload output/dashboard/latest/dashboard_payload_from_db.json
```

Save Review flow check:

```text
python scripts/journal/check_save_review_flow.py --asof 2026-06-02 --db data/journal/onejournal.duckdb
```

Streamlit launch:

```text
streamlit run src/onejournal/apps/streamlit_app.py
```

Operator rule: only DB payload is writable. CSV and Custom payloads are read-only in Phase F.

## Phase H0 ODFS Import CLI

Preferred ODFS-style journal import command:

```text
python scripts/journal/import_journal_to_db.py --asof 2026-06-02 --file docs/examples/manual_csv/fills_template.csv --reviews data/journal/reviews/manual_reviews.csv --db data/journal/onejournal.duckdb --replace
```

Compatibility command remains valid:

```text
python scripts/journal/import_journal_to_db.py --fills docs/examples/manual_csv/fills_template.csv --reviews data/journal/reviews/manual_reviews.csv --db data/journal/onejournal.duckdb --replace
```

`--file` is an ODFS alias for `--fills`. `--asof` validates imported fills and fails if fill dates do not match the requested as-of date.
## Phase I1 ODFS ingestion rule

CSV is allowed as the import and transport format only.

Raw broker exports belong under data/raw/.

Canonical normalized fill exports belong under data/normalized/fills/.

DuckDB normalized_fills, trade_episodes, trade_episode_legs, and manual_reviews are the journal source-of-truth tables.

Dashboard JSON under output/dashboard/ is generated output.

Do not build a broker-specific adapter that writes directly to Streamlit or dashboard JSON.
## Phase I3 ODFS folder rule

Raw broker files belong under data/raw/schwab, data/raw/ibkr, or data/raw/manual_imports.

Canonical normalized fills belong under data/normalized/fills when a CSV transport/export file is needed.

Do not edit raw broker exports in place.

Do not use raw broker CSV directly for dashboard, Streamlit review state, or trade_episodes.

Normalize first, validate, then import into DuckDB.
## Phase I5 operator import runbook

Use docs/operator_import_runbook.md for the safe import sequence.

The required sequence is raw evidence, normalized fills validation, DuckDB import, import audit check, DB dashboard build, dashboard contract check, then Streamlit review.

Do not use raw broker CSV directly for dashboard, Streamlit review state, or trade_episodes.
## Phase J0 Schwab execution boundary

Use docs/schwab_execution_boundary_contract.md as the rule for Schwab journal ingestion and future execution.

Current Schwab journal ingestion is read-only.

Future auto-trading must use order intents, risk gates, approval or policy checks, broker order execution, broker fill feedback, and normalized_fills journal import.

Journal scripts, dashboard scripts, and Streamlit review scripts must not call Schwab order-place, order-cancel, order-replace, or order-modify directly.
## Phase J1 Schwab adapter readiness audit

Use docs/schwab_adapter_readiness_audit.md before adding Schwab adapter code.

The first Schwab adapter should be file-based and should convert raw Schwab export CSV into canonical normalized fills CSV.

Do not build against guessed Schwab headers. Review a real Schwab export sample first.

The Schwab journal adapter must remain read-only and separate from future execution modules.
## Phase J2 Schwab legacy normalizer findings

Use docs/schwab_legacy_normalizer_findings.md before implementing Schwab parser logic.

Legacy Schwab findings confirm that security transferItems are fill-leg candidates, CURRENCY transferItems are not fill legs, raw transaction JSON should be preserved, and output must be canonical normalized fills.

The uploaded Schwab JSON transaction sample was empty, so a non-empty Schwab transaction JSON or CSV export is still required before adapter implementation.
## Phase J3 Schwab orders JSON schema contract

Use docs/schwab_orders_json_schema_contract.md before implementing the Schwab orders JSON adapter.

The fill source of truth is orderActivityCollection execution records where executionType is FILL.

The adapter must flatten OCO childOrderStrategies, match executionLegs to orderLegCollection by legId, and emit one normalized fill row per FILL execution leg.

Schwab orders JSON does not reliably carry commissions and fees, so fee enrichment should come later from Schwab transactions transferItems JSON.

## Phase J4 Schwab orders JSON adapter

Use scripts/journal/convert_schwab_orders_json_to_normalized_fills.py to convert Schwab orders JSON into canonical normalized fills CSV.

The adapter is read-only. It does not call Schwab REST APIs and does not place, cancel, replace, or modify orders.

Validate output with scripts/journal/check_normalized_fills_contract.py before importing into DuckDB.

### Schwab orders JSON daily validation rule

Use --asof when converting Schwab orders JSON for import validation.

The normalized fills contract checker validates one asof date at a time.

### ODFS runtime folder rule

Keep required ODFS runtime folders such as data/normalized/fills in place.

Do not commit generated normalized fills CSV files or raw broker files.

The folder is tracked with .gitkeep; generated files are ignored.

## Phase K1 ODFS continuous guard

Run python scripts/journal/check_odfs_continuity.py, or simply run ./bin/onejournal_check.sh.

The guard keeps required ODFS folders in place and fails if generated fills, raw broker files, output artifacts, or DuckDB runtime files are staged.

## Phase L1 Schwab transactions JSON contract

Use docs/schwab_transactions_json_contract.md before implementing Schwab transactions JSON parsing.

Schwab transactions JSON is the accounting and fee evidence source.

Schwab orders JSON remains the execution-leg source.

Do not mix these roles silently. Reconcile them later by orderId, symbol, quantity, price, and time.

## Phase L2 Schwab transactions JSON adapter

Use scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py with --asof to write one daily normalized fills CSV from Schwab transactions JSON.

The adapter is read-only and uses CURRENCY transferItems as fee evidence and security transferItems as fill-leg candidates.

## Phase L3 Schwab reconciliation check

Use scripts/journal/reconcile_schwab_orders_transactions.py to compare daily Schwab orders-normalized fills against transactions-normalized fills.

This confirms whether execution truth and accounting truth agree before DuckDB import.

## Phase M1 Schwab daily reconciliation operator

Use scripts/journal/run_schwab_daily_reconciliation.py to run the full safe daily Schwab flow.

The command converts orders and transactions JSON, validates both normalized outputs, reconciles them, removes generated CSVs by default, and runs the ODFS guard.

It does not import into DuckDB and does not call broker or order APIs.

## Phase M2 Schwab guarded daily import operator

Use scripts/journal/run_schwab_daily_import.py to run Schwab daily conversion, validation, strict reconciliation, and optional DuckDB import.

DuckDB import happens only when --import-db is explicitly provided.

The current canonical import source is transactions-normalized fills after strict reconciliation with orders-normalized fills.

## Phase M3 Schwab import idempotency guard

Use scripts/journal/check_schwab_daily_import_idempotency.py before regular Schwab imports.

It copies DuckDB to a temporary DB, runs the same Schwab import twice, and fails if the second run duplicates fills or episodes.

## Phase M4 Schwab auto-discovery import operator

Use scripts/journal/find_and_run_schwab_daily_import.py --asof YYYY-MM-DD to find raw Schwab orders and transactions files automatically.

DuckDB import still requires explicit --import-db.

## Phase M6 Schwab final daily operator workflow

This is the current recommended Schwab daily workflow.

### Place raw files

Place Schwab raw JSON exports under data/raw/schwab, using these folders:

- data/raw/schwab/<snapshot-date>/orders_all/
- data/raw/schwab/<snapshot-date>/transactions/

The operator finds files by asof date using the filename suffix __YYYY-MM-DD.json.

If multiple snapshots contain the same asof date, the operator fails safely by default. Use --use-latest-snapshot only when you deliberately want the newest path by name.

### Dry run

Run this first:

    python scripts/journal/find_and_run_schwab_daily_import.py --asof YYYY-MM-DD

Expected success markers:

    MATCHED_ROWS      : same as ORDERS_ROWS and TXN_ROWS
    ONLY_ORDERS_ROWS  : 0
    ONLY_TXNS_ROWS    : 0
    DRY RUN RESULT    : all gates passed; DuckDB import skipped
    GENERATED_CSV_CLEANUP: True
    STATUS            : OK

### Real import

Run this only after dry run passes:

    python scripts/journal/find_and_run_schwab_daily_import.py --asof YYYY-MM-DD --import-db

Expected success markers:

    IMPORT RESULT: DuckDB import and DB dashboard payload checks completed.
    PAYLOAD_PATH : output/dashboard/validation/YYYY-MM-DD_dashboard_payload_from_db.json
    GENERATED_CSV_CLEANUP: True
    STATUS      : OK

### Idempotency check

Use this when validating a date, after changing import logic, or before trusting a new raw Schwab file type:

    python scripts/journal/check_schwab_daily_import_idempotency.py --asof YYYY-MM-DD --orders PATH_TO_ORDERS_JSON --transactions PATH_TO_TRANSACTIONS_JSON

Expected success marker:

    IDEMPOTENT : second import did not duplicate fills or episodes
    STATUS     : OK

### Current canonical import source

Transactions-normalized fills are the current DuckDB import source after strict reconciliation with orders-normalized fills.

Orders JSON remains the execution cross-check.

Transactions JSON provides fee and commission evidence.

### Do not commit

Do not commit generated files from:

- data/normalized/fills/*.csv
- data/raw/schwab/**/*.json
- data/journal/*.duckdb
- output/**

The ODFS guard should remain clean after every run.

### Safety

The Schwab journal workflow does not call Schwab REST APIs.

It does not place, cancel, replace, or modify orders.

DuckDB import requires explicit --import-db.

### Duplicate raw snapshots

If duplicate raw snapshots exist for the same asof date, the operator fails safely by default. To deliberately use the newest snapshot by path name, add --use-latest-snapshot.

### Duplicate wording

When --use-latest-snapshot is provided, duplicate snapshot output is labelled DUPLICATE rather than FAIL because the operator made an explicit choice.

### DB total labels

DB_TOTAL_IMPORT_RUNS means current DuckDB total import_runs after the run, not rows imported during this run.
DB_TOTAL_FILLS, DB_TOTAL_EPISODES, and DB_TOTAL_EPISODE_LEGS are also current DuckDB totals after the run.

### No-fill trading days

NO FILL RESULT means both Schwab orders and transactions produced zero normalized fill rows. This is a clean no-op day for OneJournal. DuckDB import is skipped and generated CSVs are cleaned up.

## Hosted candidate preparation (local only; 2026-10-13)

The owner reserves **one-prod exclusively for OneBot** and requires a separate
OneJournal VPS. That VPS/provider/size/address are not yet selected. This
supersedes the earlier shared-host proposal: do not use the one-prod alias,
address, access, credentials, firewall or services for OneJournal hosting work.
The earlier host inventory is not readiness evidence for the new target.
This batch stays on the Mac: no purchase, DNS change, installation, private-data
transfer, historical backfill or accepted Mac site restart. ADR-0017's updated
profile is authoritative. Keep normal Mac use unchanged.

`scripts/web/package_hosted_release.py --destination <new-absolute-directory>`
packages **clean committed public source**: wheel, pinned hosted dependencies,
passkey-enabled static artifact, operator commands, configuration examples and
Caddy/systemd templates. Use an isolated environment with
`requirements-hosted.lock` plus the project installed; no active Mac environment
needs modification. This is a standalone 64-package hosted profile, not an
include of the accepted Mac locks; its three reviewed server patches are recorded
in `docs/mac_passkey_access_contract.md`. Install it only in a separate candidate
environment, verify dependency consistency and exact installed pins, and retain
the old candidate/lock for rollback. Do not install it into the owner's running
Mac environment. Build-tool and other advisory dispositions are not blanket
clearance. Failed candidates are retained but never activated. A Linux
environment must be built from the locks on the eventual target; do not copy
the Mac virtual environment. Verify `release.json` file hashes/source commit
before any separately authorized upload or activation. `release.json` now also
records `site_origin`, `rp_id` and `home_path`. The package renders
`deployment/Caddyfile` from the public example's origin, so a separate domain
environment override cannot silently disagree with that candidate. Only the
proxy-secret environment placeholder remains; never substitute a real secret
into a public package or command output.

The new runtime entry point is `onejournal-hosted-site --config <private-file>`.
Configuration follows `config/hosted/hosted-config.example.json`: exact permanent
HTTPS DNS origin, separate explicit local PostgreSQL journal/security connection
files, a fresh random base64url proxy secret, public static directory, and exact
optional financial authorization files. Private files use 0600 in owner-only
0700 directories. The owner approved `https://journal.onelumiq.com` on
2026-10-13 and confirmed control of `onelumiq.com`. The public example names
that origin; keep all credentials, actual connection configuration and financial
authority outside Git. Runtime configuration
must use the restricted roles, not database/schema owners. An operator-only
configuration may name owner roles for explicit setup/recovery; never use that
configuration to run the site.

Use exactly `journal.onelumiq.com` for the hosted RP/Host, HTTPS at its normal
port and `/local/today` as the landing page. The hosted root redirects there;
the accepted Mac URLs and root/demo behavior remain unchanged. Enroll a fresh
owner passkey only after actual trusted HTTPS and the hosted security store are
accepted. Do not provision a temporary domain/RP to bypass DNS readiness.

The read-only DNS check currently finds a Porkbun target for the journal name.
Keep DNS at Porkbun: no registrar transfer, nameserver change or Cloudflare
setup is required. Configure only the journal subdomain using Porkbun's
[DNS-record controls](https://kb.porkbun.com/article/68-how-to-edit-dns-records)
when the target-activation batch is approved; inspect whether the current answer
comes from an explicit record or a wildcard before making that narrow change.
When hosting is wanted, select and explicitly approve the separate OneJournal
VPS/provider/size/cost and verify its identity/address; no server is being ordered
now. The later **single target-activation batch** should explicitly authorize
the exact journal DNS record pointing to that separate target; Linux
identities/roles/cluster and public-package installation under a target-reviewed
resource budget; firewall/TLS and private synthetic access setup; and the bounded
deployed login/report/CSV, backup/restore and code-rollback checks. Never target
one-prod. Preserve root-domain/other-subdomain records. A fresh target
dependency/security check and privileged firewall disposition precede exposure;
the former OneBot host inventory provides no clearance. Owner passkey entry and
any required admin password happen privately, not in chat.

Local preparation can update the portable public package and its hashes without
uploading it. Reuse the completed synthetic PostgreSQL/API/access/recovery and
accepted Mac checks unless relevant behavior changes. Actual Linux service,
DNS/TLS, hosted device and off-server recovery acceptance wait for the separate
target. Do not invent a host address, copy an SSH alias or repeat unchanged
backup/browser suites to fill that gap.

Keep that first hosted batch **synthetic only**: no journal/account history,
financial authorizations, Mac passkey state or other existing private data is
transferred. Real-state migration/cutover and dated financial/production owner
acceptance remain separate. Until that target batch is explicitly approved,
local packaging and read-only DNS/host checks do not start DNS, TLS, deployment
or services. No historical backfill or 0029 work is included.

`prepare_hosted_store.py install-empty-journal` explicitly installs the bundled
baseline into a **new empty journal database**. `provision-access` explicitly
creates a separate fresh hosted security store and writes a new private
enrollment file. `recover-access` requires the service to be stopped, verifies
the origin/journal binding, revokes stored credentials and retains audit history.
Both access commands require `--enrollment-file <new-private-file>` as well as
`--config`. No startup migration, data import, secret printing or automatic
service restart occurs. Enrollment expires after ten minutes and is entered
directly into the trusted browser, never chat.

Local migration preparation now includes `rehearse_hosted_migration.py` in the
public package. Its required arguments are `--source-copy`, `--source-sha256`,
`--target-dsn-file` and `--receipt`. Use an owner-only (0700) temporary directory,
a closed 0600 DuckDB copy with no WAL, and its exact SHA-256. Keep the DSN file
0600 with a private parent. The target must use an owner-only temporary UNIX
socket directory and a database named `oj_rehearsal_<unique suffix>` with the
bundled baseline explicitly installed and all journal tables empty. TCP,
remote targets, normal runtime names, non-temporary source parents and replay
onto populated state are refused. There is no live migration/activation mode.

The command admits only the complete checksum-pinned migration ledger through
0028. Extra/missing tables or views, changed column types/order/nullability and
newer history schemas are refused rather than omitted. It copies in one
transaction with deferred constraints, compares typed multiset hashes and row
counts for every table and view, confirms the source hash stayed unchanged,
then checks constraints before committing. One million rows per relation is
an explicit memory bound; exceeding it fails instead of truncating. A mismatch
rolls back all inserts. The new 0600 private receipt records the proofs; never
commit or publish it. Existing receipts cannot be overwritten. A failed receipt
write after commit may leave a populated disposable target: retain it for
diagnosis and use a new target for another run, never silently clear it.

The 2026-10-13 validation used synthetic data only: exact relation reconciliation,
unchanged source, post-insert failure rollback, nonempty/unsafe/newer-schema
refusal, private/redacted receipts and matching Portfolio/Reports/CSV/journal
responses. Three focused tests passed and the owned temporary cluster was
stopped. No real private copy was read or migrated. Source files, live services,
access state and history work are outside this command. Rollback is abandoning
the disposable candidate; the original source remains authoritative.

Before real cutover, separately approve a frozen private-source export and
backed-up disposable import/reconciliation, then the exact target transfer and
activation. Preserve every source table's IDs, revisions, financial values,
timestamp/lineage and current views, including the exact accepted financial
authorization. Do not flatten history, infer missing transactions, fetch brokers
or apply 0029. Synthetic rehearsal is not that real-state migration. Keep a
single production journal writer after cutover; no two-way database sync.

The owner subsequently approved and completed that **Mac disposable-copy
rehearsal** on 2026-10-13. The existing snapshot routine obtained a read-only,
WAL-free consistent copy of the configured journal and exact financial
authorizations. The migration compared every table/view and the selected
Portfolio, report account/symbol, CSV and journal API outputs against a second
disposable DuckDB copy. Original journal bytes remained identical; the frozen
copy was also unchanged. API audit writes were confined to disposable targets.
The temporary PostgreSQL database was removed and its owned cluster stopped.
Detailed hashes, private bindings and receipt stay outside Git. No history
extension, live write, service restart or hosted transfer occurred. This is
real-data rehearsal evidence, not authority to transfer or activate that data.

On the eventual target, create independent non-owner runtime roles and private
operator roles. Apply the **journal section only in the journal database** and
the **security section only in the security database** of
`config/hosted/runtime-grants.sql`. Revoke public database access and schema
creation, grant only the named database roles, use local socket/loopback SCRAM,
and keep PostgreSQL off public interfaces. The startup validator rejects owner,
privileged or excess-write roles. A second API worker is refused by the access
lease. Sessions/challenges are revoked on restart; do not add workers silently.

Caddy terminates HTTPS at the owner-approved name and sends the exact Host plus
an overwritten private proxy header to loopback port 8766. It strips forwarded
headers; the API never trusts arbitrary forwarded peer/scheme values. Keep the
matching proxy secret in private Caddy service configuration and the separate
OneJournal private file. Caddy has no private URL access logging. The app emits
fixed failure signals without database/request values. The single-owner app
budget permits 128 requests per ten seconds, with 20 concurrent requests;
access retains its five failed-verification limit per fifteen minutes. Hosted
denials retain per-minute/action counts and one sampled event, not unbounded
individual denial rows. Accepted security events remain individually recorded;
no private IP, path or filter is retained by these controls. Templates must be owned
by the operator/root and verified on Linux before installation. Confirm actual
firewall/cloud rules, TLS and resource usage on the separate OneJournal VPS
before a later production release; the earlier OneBot inventory is not target
security clearance. Do not connect to one-prod for these hosting checks.

The prepared `onejournal.slice` limits the **combined** app, proxy, dedicated
PostgreSQL cluster and backup work to one CPU core-equivalent and 2 GiB, with
lower CPU/I/O weights. Per-service caps sit inside that shared budget; they are
not additional full-core allowances. The proxy environment drop-in names a
root-owned private environment file, never Git. Apply the PostgreSQL drop-in
only to the exact new dedicated cluster instance after verifying its identity;
never attach OneBot or a shared cluster to this slice. These are provisional
conservative limits, not sizing or performance acceptance for the unselected
separate VPS. Review its actual capacity before installation; do not carry
forward the former OneBot host's two-core assumption.
All units/drop-ins remain uninstalled and inactive in this batch.

`backup_hosted_store.py create --config <file> --image <new-absolute-file>`
creates a streaming AES-GCM authenticated encrypted backup of PostgreSQL
journal/security dumps and selected private configuration/authority companions.
The stopped-service access lease and journal writer lock protect the cross-store
snapshot. Enter a separate unique password of at least 20 characters privately;
an owner-only `--password-file` is available for a separately activated timer.
Backups preserve prior images and never apply retention/deletion. Keep passwords
independently and confirm an off-server copy before considering backup complete.

`backup_hosted_store.py restore --config <new-target-operator-config> --image
<encrypted-file> --companion-directory <new-private-directory>` authenticates
the complete archive before database writes, refuses existing target relations,
restores each new database transactionally, checks every table's content/counts
against the encrypted manifest and verifies the installed schema binding. It
exports private companions to a new directory, not their original paths. If the
second store fails, retain the first isolated restore for diagnosis and use new
empty targets for the next attempt; never overwrite live targets to retry.
Recreate/review roles and grants explicitly because dumps exclude owners/ACLs.
Run offline access recovery before owner re-enrollment after disaster restoration;
do not reactivate old credentials from a restored access backup. Nothing starts
automatically. Confirm protected reports/CSV, signed access and logout on that
isolated restoration before selecting it for any separately approved cutover.

The prepared backup timer is daily at 03:00 UTC; run the same backup service
after an approved financial publication. Its wrapper pauses/resumes **only
OneJournal and only if it was already running**; failed backup exits nonzero
with a fixed operator-attention signal and the previous images remain. It does
not upload data or reuse OneBot's backup credentials. The off-server destination
and production alert delivery/objectives must be settled before activation.
No timer is enabled in this local batch.

Rollback preparation retains the previous immutable release and exact private
configuration. Stop only OneJournal, verify the previous release's schema
compatibility and hashes, then select that version and perform the bounded
protected-path check. Do not reset a database merely to roll back code. If state
recovery is necessary, restore to two fresh targets and reconcile separately,
preserving later journal entries/audits before any approved switch. No prepared
script silently rewrites the live version pointer or runs a destructive down
migration. Final owner acceptance still requires the actual target and dated
private release; Phase 1 remains 8/12.

### Combined hosted operating proposal — 2026-10-13

**Recommendation for the eventual separate VPS, not activated policy.** Keep
one production writer, immutable public release directories and the accepted
Mac release available during cutover. Adopt the following together when the
actual target, costs and private access are ready:

| Choice | Recommended starting point | Practical limit |
|---|---|---|
| Off-server copies | A dedicated private Backblaze B2 bucket, storing only already-encrypted OneJournal backup images; independent OneJournal credentials restricted to that bucket. Keep the decryption password separately and an offline recovery copy. | Upload and remote checksum verification must finish before a backup counts as off-server. The current command does not upload; implement the narrow adapter once the destination is selected. Never use OneBot credentials or infrastructure. |
| Schedule and loss target | Existing daily 03:00 UTC preparation, plus after accepted financial publication and before state-changing maintenance. Target no more than 24 hours of journal-entry loss under a healthy daily job. | Alert when the last verified off-server copy is older than 24 hours; a failed/missed job means the target is not met. No continuous replication or zero-loss claim. |
| Recovery target | Restore and verify within four hours after the owner starts recovery with access and passwords available. | An attended objective to measure on the actual VPS, not a 24/7 staffed availability guarantee. |
| Backup retention | Propose 30 daily copies and three month-end copies. Preserve the pre-cutover backup until hosted acceptance. | No retention rule or deletion is enabled now. Backup-copy retention does not authorize deleting source evidence, financial history or audit records. |
| Failure notification | A separate Healthchecks.io check sends the owner email when the backup/verification heartbeat is late or explicitly fails. Send only generic success/failure signals. | Signal success only after remote verification. No paths, holdings, logs, account identifiers or backup credentials in notifications. The ping URL is a private secret. No messages/accounts/integrations were created. |
| Incident handling | Freeze publication on reconciliation/backup failure; retain the last accepted report with its true date. Roll back compatible code if needed; restore state to fresh targets and reconcile before switching. | Never overwrite live state as the first repair attempt or reconnect OneBot services to resolve a OneJournal outage. |

[Backblaze B2](https://www.backblaze.com/cloud-storage) offers S3-compatible
storage and scoped keys; [Healthchecks documentation](https://healthchecks.io/docs/)
describes missed-job notifications. This proposes two small managed services
instead of maintaining another backup/monitoring server. Confirm region,
current charges and owner email at target selection. Existing current-release
source evidence outside PostgreSQL must be included in the approved encrypted
backup set before promising full recovery; historical backfill stays separate.
The already tested Mac recovery remains accepted. Actual off-server transfer,
missed-job delivery and fresh-target recovery need one bounded hosted check.

### Website refresh preparation — 2026-10-13

The owner selected the existing OneBot-owned Schwab connection and deferred
activation; IBKR is a later broker adapter. The Data page now has a separate
refresh-request/status surface; reloading saved reports retains its old meaning.
The owner requires additive refresh, never a full journal rebuild: preserve old
records/reviews/releases, deduplicate repeated activity, retain corrections as
traceable revisions, and append complete dated position snapshots rather than
sum snapshot quantities. Future transaction refresh resumes verified coverage
with bounded overlap and advances it only after successful validated import.
See the precise snapshot, replay and failure rules in the web delivery contract.
These are activation requirements, not a claim that a live incremental worker
already exists. No full/reset/replacement option is exposed.
The additive API is `GET/POST /api/v1/local-owner/data-refresh`. POST accepts only
a request UUID, behind the existing owner session/origin/CSRF gate. A bare
unprotected API refuses enqueueing. The server selects the provider and the
private connection; the browser cannot choose account, endpoint, credentials,
history range or an order action.

`onejournal.refresh_requests.RefreshRequests` provides the private durable
handoff store, initialized explicitly outside Git/public assets with a 0700
parent and 0600 file. Runtime never creates it. The journal API factory accepts
an optional preconfigured store; existing Mac/hosted launchers deliberately do
not bind one yet, so the shipped endpoint reports disabled and refuses POST.
There is no misleading enabled button, automatic GET, scheduler or new token
owner. Real connection wiring and activation remain outstanding.

One active request is allowed. Repeated request UUIDs replay their recorded
state. A credential-owner worker claims once, then uses the existing bounded
current-position acquisition profile. A claimed request is never automatically
redispatched after a crash: reconcile saved evidence and explicitly fail/close
it first. The worker must pass the existing exact-byte/owner/epoch/terms validator
before recording a capture; request/run, provider/profile and configured private
connection must match. Receipt hashes remain private. `captured` means download
received, not reconciled P&L or published reports. Existing validation, owner
review, backup and release activation remain authoritative; unknown instruments
or incomplete lifecycle evidence stay withheld. No historical acquisition is
part of this request. Later incremental trades/transactions need a separate
bounded scope; IBKR needs its own verified adapter/profile, not another UI.

#### Offline request-to-evidence wiring — 2026-10-13

The installed `onejournal-refresh-offline` command (or source equivalent
`python -m onejournal.refresh_intake`) bridges an **existing, explicitly selected**
private request store to the existing position validator. It never creates a
store, enables the website feature, executes a capture or contacts OneBot.

- `--request-store <private-store> claim` claims at most one queued request and
  emits a credential-free JSON handoff containing its UUID, provider, request
  time and `current_positions` scope. `broker_execution_authorized` is false;
  the message does not replace broker/account authority. With no queued work it
  returns `request: null`. Repeated calls do not redispatch a claimed request.
- `--request-store <private-store> receive` requires `--request-id`,
  `--acquisition-root`, `--acknowledgement`, `--position-binding`,
  `--usage-policy`, `--expected-approval-id`, `--expected-owner-uid` and
  `--expected-owner-epoch-uid`. These are trusted operator/worker inputs, never
  browser parameters. Use the request UUID as the acquisition run UID.
- Intake checks owner-only files and bounds, exact manifest/response checksums,
  provider-use authority, run/owner/epoch/approval, request timing and the private
  account and complete instrument mapping. Unsupported/new instruments remain
  blocked until existing identity-intake checks resolve them. Current positions
  are converted in memory only: no holdings, P&L or journal data is written.
- The supported intake declares zero OAuth refreshes. Credential renewal and
  transport remain with the credential owner and are not activated here.
- An identical manifest can be re-received after an uncertain CLI response or
  restart without duplicating state or reopening a closed review. Conflicting
  bytes for an already recorded request fail; the first receipt remains intact.
  Different request IDs remain separate observations, not added quantities.
- If a claim process dies before its output is delivered, its durable state
  remains claimed. Reconcile owner-side evidence before explicitly resolving the
  request; do not reset it or start a second capture automatically. If intake
  fails, it exits nonzero with a fixed redacted message and leaves the claim and
  original bundle intact. No fallback, automatic retry or publication occurs.

Seven focused request/intake tests passed, including the command path with
network connections blocked, exact replay after closure, changed evidence,
wrong owner/account, stale capture, checksum/mapping rejection and duplicate
claim handling. Only synthetic temporary stores/bundles were used. No real
private configuration, request store, journal or running website was changed.

Before activation, connect this handoff to an explicitly authorized
credential-owner transport without storing Schwab credentials in OneJournal,
bind its account and capture authority, include the request store and retained
bundles in recovery, and verify one bounded read-only capture. Incremental
transactions have the offline planner/reviewer and disposable-only atomic
append rehearsal below, but still need worker and financial-read-model integration;
historical backfill remains separate. Existing financial validation, review and
append-only publication remain required after capture. Rollback is the prior
code release with the feature disabled; retain request rows and source bundles.
No schema migration, live write, broker call or OneBot change is included.

#### Incremental trades/transactions preparation — 2026-10-13

`onejournal-refresh-activity` (source equivalent
`python -m onejournal.refresh_activity`) is an offline companion,
not a website worker or broker downloader. It requires an existing owner-private
DuckDB journal and canonical Schwab account-binding file, both in private 0700
directories with 0600 files. `plan` and `review` remain read-only; `rehearse`
creates and migrates only its own temporary copy as described below.

- Shared arguments, before `plan` or `review`: `--db`, `--account-binding`,
  `--asof YYYY-MM-DD` and `--overlap-days`. Here `--asof` explicitly means the UTC
  acquisition end date, not a portfolio valuation date. Future dates are refused.
  Overlap must be explicitly configured from 1–29 days; no runtime policy or
  scheduler has been selected. Including the cutoff day prevents an intraday gap.
- `plan` reads the active confirmed v3 import and emits bounded dates, a pinned
  plan hash, whether more windows are pending, and
  `broker_execution_authorized: false`. It cannot use merely saved evidence or
  legacy date-only coverage. Each window is at most 30 dates, never starts before
  confirmed history, and never skips to the end of a longer catch-up gap.
- `review` additionally requires `--expected-plan-sha256`, `--acquisition-root`,
  `--acknowledgement`, `--usage-policy`, `--expected-run-uid`,
  `--expected-approval-id`, `--expected-owner-uid`, `--expected-owner-epoch-uid`.
  The root contains exactly the existing acquisition manifest and its two
  bounded orders/transactions JSON response files. Keep all files private.
  This consumes already transferred evidence; it does not request it.
- Review reuses exact bytes/checksums, account binding, terms and external-owner
  validation, then requires the exact planned window and a capture no earlier
  than the confirmed cutoff. A changed import/activation or account binding
  requires replanning; there is no fallback to another import or account.
- Output contains per-family new/unchanged/changed counts, no holdings, notes,
  account numbers or financial values. Keep plan/receipt hashes private too.
  Exit 0 means preparation succeeded, **not import/publication approval**;
  `candidate_only` is eligible for the disposable append rehearsal, not financial
  publication. Exit 2 means source review is required for changes/reconciliation or
  unresolved cash/event evidence. Exit 1 means validation stopped, with a fixed
  redacted diagnostic. Never ignore a nonzero exit or publish its partial counts.
- Repeating a review does not persist candidates, advance a cursor, add fills or
  write a receipt. The original database and evidence are unchanged. Missing
  incoming records do not delete existing records. Any conflicting same-identity
  observation requires source review, not an automatic overwrite.

Focused synthetic tests cover active-versus-saved imports, UTC partial-day
overlap, bounded catch-up, duplicate/new/changed identities, paired-fill
reconciliation, account/window/authority/checksum rejection, rollback-invalidated
plans and network-blocked CLI replay with unchanged database bytes. No actual
journal was opened or broker request made for this preparation.

#### Atomic activity append rehearsal — 2026-10-14

Use `rehearse` in place of `review` with the same private inputs and pinned plan.
The `--db` argument is always a read-only source: the command makes a new 0700
temporary directory and 0600 `activity-rehearsal.duckdb`, migrates the copy to
0030, appends, repeats the same append to prove replay, checks prior relation
content and removes the temporary copy. It never opens the source for writing.
Pending WAL or source lock conflicts stop; no service restart or checkpoint is
attempted. Existing pending schema prerequisites are applied only on the copy;
no historical evidence is imported or processed.

The internal writer `append_activity_copy` also refuses non-temporary paths,
symlinks/hardlinks and any filename other than `activity-rehearsal.duckdb`.
There is no override for live use. Its new immutable ledger records only unseen
normalized identities and the exact source manifest. Records and checkpoint
commit together after in-transaction predecessor checks and exact read-back.
Changed identities, incomplete reconciliation or a stale plan stop the append;
an interrupted write leaves no partial cursor. Exact replay is a no-op even
after another increment; a changed receipt for the same run fails closed.
The next plan and duplicate checks include prior successful activity imports.
Same-day checkpoints never jump ahead to the future end of the requested date.
Later complete duplicate-only captures may advance coverage with zero new rows.

Validation: focused synthetic disposable-copy checks cover append/replay,
interruption after insert, stale predecessor, correction rejection, successive
overlap without duplicates, partial-day checkpoints, rollback invalidation and
unchanged original bytes. Migration 0030 also passed on a disposable copy of the
private journal, preserving prior rows/views and removing the copy afterward.
No real capture was fetched or appended; no live migration, report or service
was changed. The private-copy check proves migration preservation; the synthetic
check proves the append state machine, not acceptance of new real financial data.

The offline financial projection below connects this retained activity to the
existing calculation/reporting types. Recovery, guarded release publication and
separately scoped worker integration remain outstanding.
Activity evidence is not yet displayed by the running website as new Trades/P&L.
Historical backfill and OneBot remain separate. Rollback for this preparation is
the previous code release; rehearsal copies are discarded, originals retained.
Migration 0030 has not been applied live or added to the hosted PostgreSQL schema.

#### Offline Trades/P&L financial rehearsal — 2026-10-14

The installed `onejournal-activity-financial-preview` command (source equivalent
`python -m onejournal.activity_financial_preview`) requires `--db`,
`--account-binding`, `--expected-checkpoint-uid` and `--account-alias`.
Use the exact retained import/checkpoint UID; when no increment exists, use the
active assembly fingerprint. The account alias must match existing released
identity where present; `Primary` remains the approved private account name.
Keep these inputs private, outside Git and browser parameters.

The source database is opened read-only under the existing WAL/lock rules. The
command creates a verified disposable copy, applies pending schema only there,
loads the exact checkpoint, builds trade episodes/executions and bounded realized
items/omissions, validates the existing Trades response models and JSON/CSV
parity, checks all copied relations for unintended writes, then removes the copy.
No provider call, live migration, history activation, financial persistence,
report authorization or service restart occurs. There is no live-write switch.

Output is a value-free status/quality/count summary. Exit 0 means the offline
pipeline completed, including explicit incomplete/reconciliation-pending states;
it is not owner acceptance of financial figures. Exit 1 means the candidate
stopped. Missing/mismatched transaction net cash, stale checkpoint, conflicting
source records or invalid lifecycle links are not converted into zeros or hidden.
Private candidate objects and reporting payloads remain in memory; this command
does not export holdings, journal notes, account identifiers or P&L into logs.

The candidate reuses the established FIFO, lifecycle, fee and execution-cash
rules. Repeated observations never become extra fills. Opening history remains
required; approved terminal instructions must bind actual retained event legs.
Earlier independent closed trades remain reportable when a later event needs
review. Any unresolved event without a matched captured trade is still exposed
as an omission. New open positions require a fresh position snapshot before
financial reconciliation; old snapshot quantities/prices do not become current
portfolio or unrealized totals. The current accepted release remains intact.

Focused tests cover confirmed close/fees, exact decimal precision, missing opens,
cash mismatch, duplicate/post-checkpoint evidence, two trade cycles, new open
position withholding, approved expiration and broken source-leg links,
unreviewed events, time-bounded omissions, checkpoint mismatch, typed Trades and
JSON/CSV parity. The verified synthetic ledger and real private-journal copy
rehearsals passed with unchanged source bytes and relations. The real-copy run
uses saved accepted evidence; it does not prove acceptance of fresh broker data.

The guarded draft/recovery package below now retains this candidate and its
source inputs. Existing order-observation variants may require source review at
incremental intake; the reporting adapter does not invent a latest-order policy.
Historical backfill, OneBot and hosted schema work remain outside this rehearsal.

#### Guarded activity report preparation and recovery — 2026-10-14

`onejournal-activity-release-preparation` (source equivalent
`python -m onejournal.activity_report_preparation`) requires `--db`,
`--account-binding`, `--raw-root`, `--expected-checkpoint-uid`, `--account-alias`
and `--output-dir`. Supply `--predecessor-authorization` whenever the source
journal contains an accepted report. Run in the existing Mac security environment
(`onejournal[security]`); the command reuses its evidence-recovery helpers.
That file must authorize the exact selected
predecessor and the identical account/alias scope; it is not authority for the
new financial result. These are trusted private operator inputs, not web fields.

Use a new absolute output directory under an existing owner-only 0700 parent,
outside Git and outside the source-evidence root. The command opens the journal
read-only, creates and migrates its own disposable copy, checks the checkpoint
and predecessor, rebuilds the candidate, and validates release coverage, unique
result identities and DECIMAL(38,27) limits without inventing acceptance IDs.

The preparation folder contains `report.json`, `realized-history.csv`,
`trades.json`, `omissions.json`, `provenance.json`, `journal.duckdb`,
`account-binding.json`, the selected `predecessor-authorization.json` when
required, and an `evidence/` tree of original checksum-matched source files.
`manifest.json` binds every file and marks `prepared_pending_owner_acceptance`,
null owner acceptance and `publication_authorized: false`. No new
`report-release-authorization.json` is created. Do not point a live release or
API launcher at this draft. It is sensitive private data, not a public artifact.

The command restores all files into a second fresh temporary directory,
validates exact hashes and current ledger/schema lineage, regenerates the
financial preview and compares report/CSV/Trades/omissions byte-for-byte. It
checks unchanged original bytes and copied table/view contents. Temporary
copies are removed; the verified private review folder is retained. Its CLI
prints status only. Exit 0 means preparation/recovery rehearsal succeeded;
financial acceptance and publication remain pending. Exit 1 means preparation
stopped. Missing or altered source files never become inferred evidence.

All intermediate directories are created explicitly as 0700 (including nested
source paths), files as 0600. Existing destinations are refused. The completion
manifest is copied last, so an interrupted output without a valid manifest
must not be used. Re-run into a new destination; earlier output is never reset
or overwritten. Verification also refuses unexpected files, unsafe paths and
fabricated accepted status.

Recovery integration: the encrypted journal image includes the entire
incremental ledger/checkpoint already. The evidence/audit backup's source
allowlist now validates the immutable incremental artifacts and exact source
manifest contracts, then requires original manifests/responses, provider-use
acknowledgements and private account bindings in addition to the existing
persisted Phase 1 evidence. Existing encrypted-image/password/USB procedures
are reused unchanged. The private draft's own complete recovery rehearsal does
not update those images or count as a new encrypted/off-device backup.

Focused checks cover the verified incremental ledger through draft creation and
restoration, exact source allowlists, release precision limits, no accepted
authorization, stale-checkpoint refusal, nested private directories, tampered
report bytes, missing evidence and destination preservation. A full preparation
and restoration using the saved private journal/evidence also passed. Only a new
private draft folder was retained; no live database, existing release, runtime,
OneBot, historical-backfill, broker, USB or hosted state was changed.

Next operating checkpoint: review the concrete draft, resolve any remaining
financial omissions/fresh-position requirements, and refresh the approved
encrypted recovery set before a separately authorized live report release and
worker activation. The existing accepted-report writer still requires genuine
financial and report acceptance; a general preparation/rehearsal instruction
does not supply it. No routine approval is needed for checks inside that scope.

#### Draft review and encrypted draft recovery — 2026-10-14

The concrete draft has been reviewed read-only against its exact accepted
predecessor. Its wider date range and admission gates do not make it a safe
replacement: some previously accepted allocations are withheld by the candidate's
lifecycle-review gate. Shared admitted allocation values agree. The private
review receipt records counts, both date ranges, the exact package fingerprint
and the traced withholding reason, without changing the preparation manifest or
creating acceptance. Reconcile the admission difference before considering a
live replacement; do not silently discard accepted results, weaken the gate or
expand into historical backfill. The currently published release stays intact.

`onejournal-activity-report-backup` (source equivalent
`python scripts/web/backup_activity_report.py`) provides `create` and `verify`.
For creation supply `--package` with the exact verified draft and `--destination`
with a **new** `.dmg` on the mounted USB. Run in your own Mac Terminal. An optional
`--receipt` must be a new file under an existing owner-only 0700 parent outside
Git; it records success, exact file count and package fingerprint, never passwords
or financial values. Verification uses `--destination` alone. Both modes require
hidden Terminal password entry; creation asks for confirmation. Keep the unique
20+ character image password independently of the USB. It is not a website-login
password. No password, token or passkey belongs in chat, arguments or scripts.

The new image is a **draft supplement**, not a replacement for the existing
journal/release, access-setup and evidence/audit recovery images. It contains
`package/` with the complete unchanged preparation folder: disposable journal,
source evidence, binding, selected predecessor authority and draft payloads.
It contains no new report authority, passkey/security database, TLS key, broker
credentials or live activation configuration. Older images are preserved.
There is no need to stop the live site or re-back up unchanged access setup to
protect this isolated draft.

The command reuses native AES-256 encrypted Mac disk images. Plaintext staging
stays in a local owner-private temporary directory; only the encrypted image
goes to USB. Before capture it checks the package and destination. It verifies
the populated capture against the unchanged source, reserves a new output
exclusively, then unlocks the **USB copy** read-only and restores into fresh
owner-only temporary files. Every file/checkpoint/lineage hash and regenerated
report/CSV/Trades/omission payload must match. Temporary mounts/copies are removed;
failure removes only this command's newly reserved unverified image, never an
older image. A failed receipt write can leave a verified image; inspect rather
than retrying creation over it.

For recovery, verify/unlock the image privately and retain any files only in a
new owner-only directory. Never overwrite live files or point a runtime at this
draft. Successful encrypted restoration is recovery evidence, not financial
owner acceptance, publication, broker permission or runtime activation.

Focused guards and one native encrypted round trip using the actual private
package passed. The owner subsequently entered the real image password in
Terminal; the USB copy unlocked, restored all exact files and reproduced the
v1 report/CSV/Trades. Its private success receipt pins that package fingerprint.
Existing images, the site, OneBot and historical evidence were unchanged.

#### Superseding offline financial correction — 2026-10-14

The earlier admission difference came from two isolated-preview defects, not
changed FIFO prices/fees or missing accepted allocations:

- Normalized Schwab **security** event legs leave currency blank (cash legs
  carry currency). Treating those security legs as unscoped events blocked
  unrelated instruments. The corrected preview uses the assembly's explicit,
  validated native-currency consensus to construct security identity, matching
  the released lifecycle reconciler. An explicit leg currency is still retained.
  This does not default monetary values, infer lifecycle approval or convert FX.
- A baseline reconciliation restriction was applied to every episode in an
  instrument scope. The corrected preview inherits that restriction only via
  the affected episode's actual fill identities, preserving it when an increment
  changes that episode's public UID. A later unresolved cycle no longer blocks
  an earlier independent, confirmed round trip. Missing opening history still
  blocks its scope; affected/unscoped unapproved events and mismatches remain
  withheld. No existing released calculator or journal projection was modified.

New calculations identify `activity-preview-v2`. Report metadata carries the
full calculation version even for an empty/unavailable response; CSV rows retain
that same full version. Preparation recovery chooses a recognized revision from
the already checksum-verified report metadata, not by retrying calculations.
Original v1 packages lacked that marker and reproduce explicitly using v1;
unknown markers fail closed. The private preparation contract remains v1 and
the new metadata marker is additive. No live/public API contract is changed.

Both focused regressions reproduced the original defects before the correction.
Financial/preparation/recovery/incremental guards pass, including changed episode
identity, affected-event withholding, legacy dispatch and unknown-version refusal.
Read-only verification of the original backed-up package still reproduces its
exact v1 fingerprint/payloads. A **new separate v2 package** was then prepared
from its saved snapshot/evidence and restored on disposable files. Comparison
retains every accepted predecessor item UID and exact value. The previous package
and all source bytes remain intact; new unresolved scopes stay explicit.

The verified USB image covers the original **v1** package, not this corrected
**v2** draft. The latter has local disposable-recovery evidence only. Its new
fingerprint still needs owner financial review and its own encrypted recovery
coverage before any separately authorized publication. Do not overwrite the v1
image, reuse its acceptance or treat this correction as live financial authority.
No further password is needed for this offline correction. Historical backfill,
broker downloads, live writes, site activation and OneBot remain out of scope.
