# Validation evidence log

Use this log to avoid repeating checks that already answered the same question.
It records bounded evidence, not a blanket claim that a feature works. Add a
new entry only after a meaningful new check. Keep private data and machine-
specific private paths out of this file. Evidence from another worktree applies
here only when the listed code hashes and conditions match.

## 2026-10-16 — combined website upload to saved financial release

- **Scope/authority:** owner requested automatic Journal, Portfolio and Reports
  publication after upload validation, with OneBot, historical backfill and VPS
  separate, and explicitly approved Mac installation, enablement and restart.
  The new private opt-in defaults off; ordinary staging remains unchanged.
- **Code checked:** `src/onejournal/manual_financial_refresh.py` SHA-256
  `e8b538c8aa5934964e8adf06620e923f809d61d68a38e1061fbef3dd0906afc5`;
  `src/onejournal/manual_capture_upload.py` SHA-256
  `9039e0650dc2a88dc305f10478c16c4d190ccf4ca59a9aae6c8aec5a572404e1`;
  `src/onejournal/local_web.py` SHA-256
  `5d1e7ac096997cc99911e72de74b26f4333ceaf0c9e43a41b65be095399ad6a7`;
  `src/onejournal/api/local_owner_journal.py` SHA-256
  `828fa0761bdaf323b95293cda573384e3a0c4b110dda0c36835d0de27a6fe119`.
- **New synthetic evidence:** focused `test_manual_financial_refresh` cases
  proved paired HTTP upload, exact decimal realized result, current Portfolio,
  current report/CSV selection, duplicate replay, selection after restart,
  denied unprotected access, invalid bytes/owner rejection and complete original
  database preservation after an injected report-save failure. The existing
  default staging case and extended private-config all-or-none case passed.
  Only failed new fixture assertions were repeated: correct provider terms
  artifact, signed sell quantity, actual broker basis field and decimal-scale
  comparison. No financial validation rule was relaxed.
- **Private integration:** one completed HTTP rehearsal on a disposable copy
  used the already retained position/activity evidence and an existing accepted
  predecessor. Same-app reporting reads, exact replay and selection in a newly
  constructed app passed. Original journal bytes were retained unchanged.
  The private receipt binds the four source hashes above. An initial operator
  attempt used the wrong activity subdirectory and stopped before copying or
  writing any journal; only that new integration attempt was corrected.
- **Frontend:** the two focused `web/tests/financial-upload.test.mjs` tests and
  TypeScript no-emit check passed. The build completed with the existing
  lockfile-matching dependencies. The initial build-tool lookup was corrected
  to reuse that existing installation; no dependency upgrade was performed.
  Saved synthetic renders show the two labelled file selectors and action at
  desktop, tablet and mobile sizes, without horizontal overflow. The mobile
  render was inspected. These are not screenshots of private financial data.
- **Reuse/limits:** reused the established valuation, quantity, lifecycle,
  Journal projection, security and encrypted recovery evidence. No unchanged
  full suite or broker call ran. This entry proves the new connection on copies,
  not a new live financial import or owner browser acceptance. The installed
  runtime activation is a separate outcome. Repeat only affected evidence if
  these components, their financial contracts, input class or environment change.

## 2026-10-16 — live latest captured Portfolio/Reports publication

- **Authority/source:** owner explicitly requested updating Portfolio and Reports
  with the latest validated retained data, keeping OneBot, historical backfill
  and VPS separate. The earlier conditional publication choice applies after
  financial validation. Calculation producer is committed `3ccc986`; its exact
  code hash and source/checkpoint/result fingerprints are bound in the private
  preparation plan. No new broker request or migration was required.
- **Published result:** the complete 68-position observation and report coverage
  now use October 15, New York market date, from the October 16 UTC capture.
  There are 260 reportable realized results and 83 withheld entries. All 257
  previously published results match exactly, and a multiset comparison confirms
  the same 83 withheld economic scopes, statuses and reasons. Saved valuation
  uses the original capture instant and unchanged freshness/precision rules;
  publication time does not turn these prices into live prices.
- **Live operation:** stopped only the previously identified OneJournal Mac
  process. Created a fresh owner-private rollback journal/configuration/launcher
  copy, verified exact database bytes and opening the retained report, then
  appended the new snapshot, valuation and immutable combined report. Typed
  read-back and the existing Portfolio, report breakdown, realized-history and
  CSV APIs passed against the saved live target. Every non-financial-publication
  relation, including Journal entries/reviews/checkpoint and history, matched its
  pre-write proof. Previous report releases and their results were preserved.
- **Runtime activation:** switched only the private financial authorization paths
  in a new configuration and restarted the existing compatible protected runtime.
  The unchanged frontend/static release was reused without another build.
  Trusted HTTPS, served-shell hash, enrolled-passkey status and the actual process
  selecting the new configuration passed. Private plan, publication, rollback
  and runtime receipts are retained outside Git. No personal values or private
  paths are copied here.
- **Reuse/limits:** reused the focused quantity-reconciliation checks and the
  single new combined disposable-copy API/CSV result recorded below. No unchanged
  full suite, upload rehearsal, encrypted recovery exercise or security suite was
  rerun. This proves the dated saved release and runtime switch, not live broker
  prices, complete earlier account history, VPS deployment or owner visual
  acceptance after reloading the browser. Recheck only the affected binding,
  financial result or runtime when its inputs or code change.

## 2026-10-16 — Mac saved-Journal live activation

- **Authority and release:** owner explicitly approved the fresh rollback copy,
  live Journal import and protected Mac restart, then separately approved existing
  migrations 0029 and 0030 after the live target was found at 0028. Application
  source is `5c8b815fbbdd906b4a5b5ef768e054e884312fa9`. The new isolated runtime
  imports its installed wheel and matches the pinned Python dependencies; the
  previously missing pinned timezone package was installed only in that runtime.
- **Fresh rollback:** copied the closed live journal under a read-only lock;
  exact source/copy file hashes matched. Opening the copy reproduced its existing
  relation proofs. The previous launcher/configuration were retained alongside
  the private rollback receipt. Previous encrypted backups were not replaced or
  retested. No existing process was stopped: the site port was initially free.
- **Live operation:** applied only pending 0029/0030 through the existing ordered
  migration operator, preserving every prior schema-ledger row. All newly added
  historical-evidence tables stayed empty. The already captured package then
  passed the configured intake and committed 118 activity additions, with 310
  trades and 619 executions returned by the saved Journal. Existing search and
  latest-trade API reads passed against the live target. No broker request or
  historical backfill was performed.
- **Preservation:** compared every pre-existing relation except the explicitly
  permitted fills/import-run/checkpoint tables and the additive schema ledger.
  Existing history, notes, Portfolio and Reports records matched their rollback
  proofs exactly. The Portfolio/Reports authorization files retained their exact
  hashes. The subsequent Journal reads added only normal value-free read audits.
- **Actual runtime:** updated the private launcher and started the approved wheel
  and static build in a Mac Terminal. The selected 58-file release inventory,
  trusted localhost HTTPS, served shell hash, existing enrolled-passkey anonymous
  session status and private Journal HTTP 401 denial passed. The service listens
  only on loopback port 4173. Import, rollback and runtime receipts are saved
  privately outside Git; no private paths, identifiers or financial values are
  included here.
- **Limits/reuse:** this proves the live import and protected runtime activation,
  not a new Portfolio/Reports release, broker download, hosted acceptance or owner
  sign-in/visual acceptance of the changed Journal screen. The earlier synthetic
  save/review/replay/rollback checks were reused. No unchanged suite, private-copy
  rehearsal or encrypted recovery exercise was repeated. Recheck only affected
  behavior when code, selected package, binding, database or release changes.

## 2026-10-16 — latest captured Portfolio/Reports preparation

- **Changed gap:** the newly saved Journal activity had advanced, but Portfolio
  and Reports still selected their previous October 10 release. The report
  preview also still used the older position evidence. An optional exact-snapshot
  quantity check now connects the latest position observation to that preview
  without changing existing calculation behavior when no snapshot is supplied.
- **Code:** `src/onejournal/activity_financial_preview.py` SHA-256
  `3c193e52e7d1d54015c94a5d366171fcb5b98521b63b03a9eac26fe3c88c4d18`;
  `tests/test_activity_financial_preview.py` SHA-256
  `8ea6226922edc31c9919c0c187bea0d05f20e7225e1f046f3b6a977998b3455e`.
- **Smallest changed checks:** the new
  `test_latest_snapshot_reconciles_partial_close_without_promoting_missing_evidence`
  and existing `test_new_close_reconciles_fees_and_reuses_trade_report_contracts`
  passed (2 focused synthetic tests, security Python runtime). Quantity match
  admitted the reconciled partial close; wrong quantities remained pending.
  Wrong account, incomplete snapshot and activity after the snapshot failed.
  The existing no-snapshot calculation remained unchanged. No full suite ran.
- **Private publication preparation:** reused the retained October 16 capture,
  its approved account/instrument binding, existing valuation precision and age
  policy, and the confirmed Journal checkpoint. All 68 positions had available
  basis, value and unrealized result. The dated valuation is for October 15 New
  York time, evaluated at the actual retrieval instant; it does not assert
  current prices at publication time. The new report has 260 admitted results
  and 83 withheld entries, preserves all 257 previously published results exactly,
  and has coverage ending October 15. Existing financial holds were retained.
- **New integration check:** persisted the combined candidate on one disposable
  journal copy, then read Portfolio, current report breakdowns, realized history
  and CSV through the existing APIs. Typed read-back, CSV count and preservation
  passed. An initial operator call omitted required report date filters and was
  corrected; the failed new integration check alone was repeated. Prior
  upload/replay, backup restoration, frontend build and security tests were reused.
  The source journal was unchanged, and no broker access occurred.
- **Limit/invalidation:** this entry proves preparation, not live publication or
  runtime activation. Saved private candidate/plan files bind the source and
  calculation hashes. Repeat only affected behavior if code, captures, account
  binding, financial contracts or environment change; the live append/read-back
  and configuration switch still require their own operational receipt.

## 2026-10-16 — distinct local Trades and Journal views

- **Code checked:** `web/app/journal/local/page.tsx` SHA-256
  `162201d290e6462486f4a7822728b791471991edc857f14a1bf03184ca49dec1`;
  `web/app/globals.css` SHA-256
  `c6cedfdf1cb36083d063ed183db39b253d9432ebe384883a9d126a280c8d109a`;
  `tests/test_local_owner_journal_api.py` SHA-256
  `215d680ab505c31dffdb1e7aba72392a715c7b86594e515b90dec4d725a00d43`.
- **Reason:** the two routes shared the same trade-heavy screen, burying journal
  entries and reflections. The local Journal now puts saved entries first and
  shows a standalone or trade-linked reflection form without first selecting
  an old trade. Trades retains execution detail and the entry-reason review
  form. One focused synthetic API test proved standalone save, private search
  metadata, and intentional full-entry read. The production frontend build
  passed with existing local dependencies; no private journal or broker data
  was read for these checks.
- **Not proved:** no live browser or owner acceptance, recent-trade import,
  journal database change, report publication, or runtime activation. A change
  to these UI files or their API contract invalidates this build evidence.

## 2026-10-16 — validated upload to saved Journal

- **Scope/revision:** focused continuation of `27f0ee9`; new v2 incremental
  artifact retains the Journal read model, confirmed fills and checkpoint in one
  transaction. No new migration. Existing staging and v1 evidence remain valid.
  Activation defaults off with `manual_capture_save_journal: false`.
- **Pinned code:** `journal/activity_journal.py` SHA-256
  `a0f783ddf36c1d60c7458e3890bdef912d71f95a0cca55de2697db289026509e`;
  `journal/activity_refresh_repository.py`
  `3d8bd6d30b9a829a2b2ecec621b13efac96a7bc7cd894c0634e2b8dbb9917392`;
  `manual_capture_upload.py`
  `03541f11dd8e64b8502046498f75db838236308c64f8afad9ab2c07dbf955c8d`;
  `api/local_owner_journal.py`
  `a558485ae0e14403f3f7607c2ea50806185009ccecfdc09a72ae1b7905f19469`;
  `tests/test_activity_journal_upload.py`
  `74f5090b6d30b16876a9147a4c38794dd3a47496ea8b48c661027f84c1c5f6f3`.
  Source module paths are relative to `src/onejournal/`.
- **New synthetic journey:** `PYTHONPATH=src:tests:. python -m unittest
  test_activity_journal_upload -q` passed (2 tests, Mac security runtime).
  An HTTP upload saved a newly confirmed execution; existing search and trade
  APIs returned it immediately. Entry-reason review, linked lesson save/read,
  exact upload replay and a new app's read of the retained view passed. Injecting
  a failure after new fills were inserted rolled back fills and checkpoint.
  The original source bytes were unchanged. Network connections were forbidden.
- **Focused compatibility:** the existing default staging/replay test and the
  extended all-or-none private-config test passed. The changed frontend receipt
  test passed with `node --experimental-strip-types --test
  web/tests/manual-capture.test.mjs`. TypeScript no-emit check and static build
  passed using existing local build dependencies. The earlier standalone-note
  evidence above was reused, and no unchanged full suite or backup was rerun.
- **Why new checks ran:** prior evidence covered staging/copy previews, not the
  saved-Journal writer. The initial new check caught timezone-naive serialization;
  UTC was retained. The note fixture was corrected to use the existing entry
  type/header contract. A build invocation used an unsupported root flag and was
  corrected without changing application code. Only affected checks were repeated.
- **Private input:** one disposable-copy run used the already captured activity
  package and existing private journal, calling the new writer and existing API.
  It saved 118 new records and read 310 trades / 619 executions. API startup,
  search and latest trade read passed; the source journal was retained exactly.
  No source identifiers, raw responses, values or private paths are recorded here.
- **Limits:** not live import, runtime activation, browser/owner acceptance,
  Portfolio/Reports publication, broker download, history backfill or VPS proof.
  Automatic approval review rejected direct live wiring; this change leaves its
  activation flag off. Repeat only the affected check if the listed code, typed
  Journal relations, financial/lifecycle contracts, capture class or runtime
  changes. A newly authorized live import still needs its own commit/read-back.

## 2026-10-15 — staged position to disposable valuation and snapshot append

- **Code tested:** `src/onejournal/staged_position_rehearsal.py` SHA-256
  `69716cb3f7b8f398803c5e3ea007dc9a832c914184b770116b1e7fca7960babf`;
  `tests/test_staged_position_rehearsal.py` SHA-256
  `9f992bf1931d39a78dd0bbaa727bc35408580765ef614909ed4bba01ff103ef1`.
- **Focused synthetic check:** one test passed in the Mac security Python
  runtime. An exact privately staged position package used the previously
  accepted release's valuation policy, appended a new snapshot and valuation
  on a disposable copy, and read it back. Missing tax-lot basis returned a
  financial hold; stale evidence failed. The original journal bytes were
  unchanged, and network connection was forbidden throughout. Early runs of
  this same new test exposed incorrect synthetic completion time and database
  file permissions, then an intentionally missing basis; the fixture was
  corrected, not the safety checks. No full suite or private rehearsal ran.
- **Not proved:** no private capture, live journal append, new Portfolio release,
  report update, backup, website worker, browser journey or broker access was
  exercised. The saved Mac website remains unchanged.
- **Reuse boundary:** repeat the smallest affected check if these code hashes,
  capture or valuation contracts, input class or runtime changes, or before a
  newly authorized consequential live action.

## 2026-10-15 — staged activity to disposable financial preview

- **Code tested:** `src/onejournal/staged_activity_rehearsal.py` SHA-256
  `25387512bdb61474ec21e0439fd2b457d9727d821dc3a024b2f9260a22820132`;
  synthetic integration case in `tests/test_refresh_activity.py` SHA-256
  `8bec43f09e583ee5380e28722b66a0bb3aa20ba1973fb4cb16ac64ce4a032949`.
- **Focused check:** one existing synthetic active-import case, extended to stage
  an exact approved activity pair, passed in the Mac security Python runtime.
  It reached append and financial preview on a disposable journal copy, with
  no network connection and no change to the source journal. A review-required
  result stopped before any copy writer; changing the independent approval
  rejected the staged package. No existing full suite was rerun.
- **Environment note:** the first attempt used a general Python environment
  missing the pre-existing `webauthn` dependency and failed after the new
  assertions. The same focused case passed under the project's Mac security
  runtime; no dependency or application code was changed to hide that failure.
- **Not proved:** no private capture was processed, no current-position snapshot
  was appended, and no live journal, saved report, website session, backup or
  broker service changed. The website refresh is still inactive.
- **Reuse boundary:** repeat only if the staged connector, dependent contracts,
  input class, or runtime changes, or before a consequential live action that
  needs its own evidence.

## 2026-10-14 — Mac manual capture file picker and private staging

- **Code tested:** `src/onejournal/manual_capture_upload.py` SHA-256
  `3e91ff7406fc2d7ce91b41a7d81d74a65e03fdb19d72f499ea52f85467c70027`,
  `src/onejournal/local_web.py` SHA-256
  `56708a074a111255e33336c9e3dd75828c26baec605363a1262b723b0fc09155`,
  `src/onejournal/api/local_owner_journal.py` SHA-256
  `8bc2e531820344922b8bfe24da2436b270c6e87498ccb5cd80b2cfb2a884af21`,
  `web/components/data-refresh.tsx` SHA-256
  `2b35e73b7cbe17b86e5fbfb4aff5fd0774bea9b7b02042ed1cb9fd1447b483c1`,
  and `web/lib/manual-capture.ts` SHA-256
  `72e9dbaedd9ab26ed3157ff8585b62b6f376a0cd131283da96369219715f9f54`.
- **Synthetic checks:** focused upload/authorization/configuration tests passed
  (9 tests), plus one existing API-factory integration test. Exact position and
  activity packages were privately staged; exact
  replay did not duplicate files. Unprotected route access, changed bytes,
  browser-supplied approval, wrong private account, malformed input, oversized
  input and incomplete/unsafe configuration were rejected. TypeScript type
  check, focused lint and a disposable static build passed. No private capture
  or financial value was used in these checks.
- **Visual limit:** the disposable browser preview reached the expected passkey
  gate without a private test service, so the new file picker was not visually
  inspected at desktop/tablet/mobile sizes. This must be checked when the Mac
  upload is configured and activated; the current site was not restarted.
- **Not proved:** no live package upload, account-owner acceptance, journal
  append, checkpoint advance, financial reconciliation, report publication or
  browser end-to-end refresh. Existing saved Portfolio and Reports are unchanged.
- **Reuse boundary:** repeat only the affected check if these code hashes,
  security wrapper, upload contract, private setup or input class changes.

## 2026-10-14 — manual capture authority boundary

- **Code tested:** `src/onejournal/refresh_capture_authorization.py` SHA-256
  `e411396502ed528071625ae554e92cd226f0199c226bcf6861a3cf2eccf3b418`;
  synthetic tests in `tests/test_refresh_capture_authorization.py` SHA-256
  `4fb08628507608393b6ec4499812a7c0f5d23f2e68e8fd00228f18ca3f53da3c`.
- **Synthetic check:** focused module, 3 tests passed. An owner-private record
  approved only the exact existing-form capture package. Altered response or
  manifest bytes, changed owner, public/misplaced approval file, and a browser
  package containing an approval file were rejected.
- **Not proved:** no private capture was uploaded, no live account was checked,
  no journal or release was written, and no website refresh was activated. The
  backend upload, account binding, financial append, release and recovery path
  remain separate unfinished work.
- **Reuse boundary:** do not repeat these synthetic checks if the listed code,
  capture authorization contract, and verifier remain unchanged. Recheck the
  smallest affected layer when any of those changes or an upload is wired.

## 2026-10-14 — incremental activity correction (separate working branch)

- **Code tested:** `src/onejournal/refresh_activity.py` SHA-256
  `b1a2bc74bfa748a44371f4d295497847847b37d55586bf1fde337c0bd1402c05`,
  `src/onejournal/journal/activity_refresh_repository.py` SHA-256
  `737aacd72d62d82d9bd6b41687b6616dc1418fe159597cc1688cce02eca73d2d`,
  and `tests/test_refresh_activity.py` SHA-256
  `bf58bcccff63af74855a886f60a86f7455c7172d2906b4837388444c9cb4a975`.
- **Synthetic check:** focused `test_refresh_activity` unittest module: 6 tests
  passed. This includes refusal of altered financial fields and acceptance of
  only the narrowly reviewed, unfilled order replacement.
- **Private offline check:** one existing capture passed read-only review and an
  append plus exact replay on a disposable journal copy. The command reported
  that the original journal was unchanged. No new broker request was made for
  this check. The command output was observed in this task; no separate durable
  private receipt was saved.
- **Not proved:** no live journal append, saved position binding, report release,
  website-triggered refresh, or browser end-to-end refresh. The Mac website's
  Refresh button remains inactive; a manual disposable rehearsal does not
  close that product gap.
- **Reuse boundary:** do not repeat the same synthetic or private rehearsal if
  the tested code hashes, relevant contracts, source capture, and environment
  remain unchanged. Recheck the smallest affected layer if any of those change
  or before a newly authorized live action that requires fresh evidence.

## 2026-10-14 — why the Mac Refresh button is inactive

- **Source check, not another data test:** `local_web.py` SHA-256
  `6c09206ec7d2d83b7a9b8a54048bbe32cb7cc914b0253cf69a079d8d5d741780`
  starts the local API without a refresh request store. `mac_static_site.py`
  SHA-256 `69432e3f39accce82498ca4759494d8dcdbcb7aeb17d7d0c68533adc80ca9528`
  uses that same app factory. The API consequently reports `enabled: false`.
- **Actual missing capability:** `refresh_requests.py` SHA-256
  `30f3b984f09ea7fb6a5a939fad87837a7dc579734a835ab829d390078271319b`
  can save and claim a request, and `refresh_intake.py` SHA-256
  `d3312cfa3214de641990e8d809d6d7e310fd075743ffeff0813e6d783682ddc8`
  can validate a transferred position bundle, but neither runs a OneBot-owned
  broker capture or updates the live journal and saved reports. Merely binding
  the queue would make the button accept a request that cannot finish.
- **Next acceptance evidence:** one owner-initiated website request must reach
  a separately authorized, bounded read-only capture, validate and append new
  records without a full rebuild, and change the saved release automatically
  only when its complete financial validation passes. A hold must retain the
  previous release. Existing offline rehearsals do not establish this
  browser-to-broker-to-journal behavior.

## 2026-10-14 — credential-owner handoff check

- **Source check:** the inspected OneBot repository has a general Schwab CLI
  with read operations and order place/cancel/replace operations in the same
  client module. No OneJournal-specific, narrow website-to-OneBot capture
  service was found in that repository. Previous OneJournal private capture
  runners are bounded to reviewed individual runs, not an always-on website
  handoff. This was read-only inspection; no OneBot file or service changed.
- **Consequence:** giving the website a general OneBot CLI/SSH capability would
  cross the existing separation and expose order-capable tooling. A direct
  one-click refresh requires either a new narrow read-only credential-owner
  handoff or an explicitly approved transfer of token ownership. Neither is
  authorized or implemented by the current request queue.
- **Owner direction after this check:** retain manual exports. Do not build a
  website-to-OneBot trigger or transfer Schwab credentials. The next workflow
  starts from an explicitly supplied private export on the Mac. The owner
  selected the existing checksum-verified capture package and a website file
  picker, not a generic Schwab CSV. The current package is a private directory
  with a manifest and response files; its acknowledgement is a separate
  private file. This selection defines the input, not a working upload or
  financial publication. The automatic publication choice still applies only
  after complete validation.

## 2026-10-16 — bounded manual capture correction and copy rehearsal

- **Code tested:** `src/onejournal/refresh_activity.py` SHA-256
  `6aa852b84804a0855064a129827d5e33b35bb47e71310f0181883095f3f26520`;
  `tests/test_refresh_activity.py` SHA-256
  `8bbc5b591a368f192128296116a9043b3ef11a6ee912f5e533914883bfa24281`.
- **Why repeated:** the new October 16 private capture exposed two previously
  unsupported, unfilled conditional-order closing transitions. Earlier tests
  covered only pending-activation replacement, so that evidence did not cover
  this input class. Two focused synthetic tests passed, including economic-field
  and linked-fill rejection. The saved capture then passed read-only activity
  review with three narrowly reviewed order states. Append plus exact replay
  passed on a disposable journal copy; the source journal was unchanged.
- **Position evidence:** the complete private position response had seven
  newly observed instruments and three prior mappings absent. Each new identity
  was supported by one verified transaction identity observed no later than
  the position capture; retained identities did not conflict. A new owner-only
  binding was saved separately from the earlier binding. Credential-free
  position intake passed for all 68 positions. The valuation persisted and read
  back on a disposable copy when evaluated at the exact capture instant.
- **Limit:** the accepted position release has a zero-second snapshot-age
  allowance. A later-time valuation correctly failed as stale; the copy result
  does not authorize treating this snapshot as current now. No live append,
  release publication, website activation, broker request, OneBot change or
  historical backfill occurred in this correction/rehearsal step. The three
  read-only broker requests and zero renewal were completed in the separate
  approved capture step; its private source bundles were preserved.
- **Reuse boundary:** reuse these checks only while the cited code, private
  source bundles, account and position bindings, active journal revision and
  freshness policy match. A newly authorized live action or changed evidence
  needs its smallest affected check, not another full rehearsal by default.
