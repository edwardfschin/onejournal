# Validation evidence log

Use this log to avoid repeating checks that already answered the same question.
It records bounded evidence, not a blanket claim that a feature works. Add a
new entry only after a meaningful new check. Keep private data and machine-
specific private paths out of this file. Evidence from another worktree applies
here only when the listed code hashes and conditions match.

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
