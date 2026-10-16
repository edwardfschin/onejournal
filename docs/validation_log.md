# Validation evidence log

Use this log to avoid repeating checks that already answered the same question.
It records bounded evidence, not a blanket claim that a feature works. Add a
new entry only after a meaningful new check. Keep private data and machine-
specific private paths out of this file. Evidence from another worktree applies
here only when the listed code hashes and conditions match.

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
