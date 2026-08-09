# OneJournal Journal Domain Contract v1

## Status and purpose

Status: **Accepted for local implementation and temporary-copy validation.**

This contract defines the minimum durable journal model for UXJ-01. It replaces
neither the current `manual_reviews` compatibility table nor any financial,
lifecycle, broker, or execution contract. Applying migration `0005` to the
runtime journal remains a separate, explicitly approved operation.

## Invariants

- Journal content is owner-authored private evidence.
- Broker and financial source records are never edited to change journal text.
- Stable logical identities are separate from append-only content history.
- Earlier revisions and reviews are never silently overwritten.
- An episode rebuild may change derived episode state but must not delete linked
  journal entries or reviews.
- Episode linkage is a durable logical reference, not a delete-cascade foreign
  key. A missing post-rebuild episode is an explicit reconciliation exception.
- System-derived strategy classification and owner-defined journal strategy are
  separate fields.
- Attachment bytes, absolute paths, public URLs, credentials, and raw broker
  payloads are not stored in DuckDB.
- Journal writes do not call broker APIs or alter orders.

## Logical relationships

```text
trade_episodes (derived canonical episode)
    1 -> many journal_reviews (append-only structured review events)
    1 -> many journal_entries (optional link; an entry may start unlinked)

journal_strategies
    1 -> many journal_entry_revisions (optional owner-defined strategy)

journal_entries
    1 -> many journal_entry_revisions (append-only content/state snapshots)
    many <-> many journal_tags (through append-only tag events)
    1 -> many journal_attachments (metadata only; feature remains disabled)

manual_reviews
    current Streamlit compatibility projection of latest structured review
```

## Persisted records

### `journal_entries`

One immutable identity row per logical entry.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `entry_uid` | UUID | yes | Stable entry identity. |
| `created_at` | TIMESTAMP | yes | UTC-normalized creation instant. |
| `created_source` | VARCHAR | yes | `streamlit`, `import`, `operator`, or a later approved authenticated API source. |

No mutable prose lives in this table.

### `journal_entry_revisions`

One immutable full content/state snapshot per revision.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `entry_uid` | UUID | yes | Parent logical entry. |
| `revision_no` | INTEGER | yes | Positive, contiguous revision number per entry. |
| `episode_uid` | VARCHAR | no | Linked canonical episode; null permits pre-trade/general entries. |
| `entry_type` | VARCHAR | yes | Approved type listed below. |
| `strategy_uid` | UUID | no | Owner-defined strategy; does not replace episode classification. |
| `title` | VARCHAR | no | Short owner-authored title. |
| `body` | VARCHAR | yes | Owner-authored narrative; may be empty for a structured placeholder. |
| `occurred_at` | TIMESTAMP | no | When the journalled event occurred, distinct from save time. |
| `entry_status` | VARCHAR | yes | `active` or `archived`; no hard-delete state is approved. |
| `change_reason` | VARCHAR | no | Owner-provided explanation for an edit. |
| `created_at` | TIMESTAMP | yes | Revision creation instant. |

Primary key: (`entry_uid`, `revision_no`). Current state is the highest valid
revision number, ordered by number rather than timestamp.

Approved initial `entry_type` values:

- `pre_trade_plan`
- `entry_thesis`
- `execution_review`
- `exit_review`
- `post_trade_reflection`
- `weekly_review`
- `monthly_review`
- `mistake`
- `lesson`
- `note`

Unknown types fail closed; they are not converted to `note` silently.

### `journal_reviews`

One immutable structured review event per save.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `review_uid` | UUID | yes | Stable event identity. |
| `episode_uid` | VARCHAR | yes | Reviewed canonical episode. |
| `review_status` | VARCHAR | yes | Existing four-state review contract. |
| `setup_quality` | VARCHAR | yes | Existing five-value setup-quality contract. |
| `entry_reason` | VARCHAR | no | Compatibility structured field. |
| `notes` | VARCHAR | no | Compatibility structured field. |
| `supersedes_review_uid` | UUID | no | Immediately prior review event when one exists. |
| `source` | VARCHAR | yes | `legacy_backfill`, `streamlit`, `import`, or approved API source. |
| `created_at` | TIMESTAMP | yes | Review save instant. |

Initial `review_status` values remain `unreviewed`, `needs_review`,
`mistake_review`, and `reviewed`. Initial `setup_quality` values remain
`unknown`, `good`, `acceptable`, `poor`, and `mistake`. Changing either set is
a separate contract change.

The current review is the event that is not superseded by a later event in the
same episode chain. Competing heads or a broken supersession chain are errors,
not tie-broken by timestamp.

### `journal_strategies`

Owner-defined reusable journal strategy catalog.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `strategy_uid` | UUID | yes | Stable owner-defined strategy identity. |
| `name` | VARCHAR | yes | Display name. |
| `normalized_name` | VARCHAR | yes | Case/whitespace-normalized uniqueness key. |
| `description` | VARCHAR | no | Owner-authored definition/checklist context. |
| `status` | VARCHAR | yes | `active` or `archived`. |
| `created_at` | TIMESTAMP | yes | Creation instant. |
| `updated_at` | TIMESTAMP | yes | Last catalog metadata update instant. |

System `trade_episodes.strategy_type` and `strategy_label` remain unchanged.

### `journal_tags`

Reusable typed classification vocabulary.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `tag_uid` | UUID | yes | Stable tag identity. |
| `tag_type` | VARCHAR | yes | `general`, `mistake`, or `lesson`. |
| `name` | VARCHAR | yes | Display name. |
| `normalized_name` | VARCHAR | yes | Unique key within `tag_type`. |
| `status` | VARCHAR | yes | `active` or `archived`. |
| `created_at` | TIMESTAMP | yes | Creation instant. |

### `journal_entry_tag_events`

Append-only assignment history.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `tag_event_uid` | UUID | yes | Stable event identity. |
| `entry_uid` | UUID | yes | Logical entry. |
| `tag_uid` | UUID | yes | Reusable tag. |
| `sequence_no` | INTEGER | yes | Positive, contiguous sequence per entry/tag pair. |
| `action` | VARCHAR | yes | `assign` or `remove`. |
| `created_at` | TIMESTAMP | yes | Event instant. |

Current membership is the latest action for each (`entry_uid`, `tag_uid`) pair.
It is ordered by `sequence_no`, not timestamp or event identity.

### `journal_attachments`

Private metadata only. Rows cannot be created by the product until UXJ-05 is
approved.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `attachment_uid` | UUID | yes | Stable metadata identity. |
| `entry_uid` | UUID | yes | Parent journal entry. |
| `storage_key` | VARCHAR | yes | Opaque private-store key, never an absolute path or public URL. |
| `original_filename` | VARCHAR | yes | Sanitized display filename. |
| `media_type` | VARCHAR | yes | Validated media type. |
| `byte_size` | BIGINT | yes | Non-negative content length. |
| `content_sha256` | VARCHAR(64) | yes | Lowercase content hash for integrity/deduplication evidence. |
| `captured_at` | TIMESTAMP | no | Source capture instant when known. |
| `created_at` | TIMESTAMP | yes | Metadata creation instant. |

Retention and deletion fields are deliberately absent until policy is approved.

## Compatibility projection

During the Streamlit transition:

```text
Save Review
-> validate episode and review values
-> begin one DuckDB transaction
-> append journal_reviews event
-> update manual_reviews current projection
-> commit
-> rebuild existing dashboard payload
```

Failure of either write rolls back both. The legacy CSV importer may create a
`legacy_backfill` review event only when the incoming values differ from the
current review; replaying identical CSV evidence must not add another event.

## Representative examples

### Pre-trade plan linked after execution

1. Create `journal_entries(entry_uid=A)`.
2. Append revision 1 with `entry_type=pre_trade_plan`, `episode_uid=null`, and
   the intended thesis/risk narrative.
3. After confirmed activity creates episode `E`, append revision 2 linking A to
   E. Revision 1 remains unchanged.

### Corrected post-trade lesson

1. Entry B revision 1 records a post-trade lesson.
2. The owner corrects wording and supplies a change reason.
3. Entry B revision 2 becomes current; revision 1 remains auditable.

### Mistake taxonomy

An entry uses `entry_type=mistake` for the narrative and receives reusable
mistake tags such as `late_entry` and `oversized_position`. Removing a tag
appends a `remove` event; it does not delete assignment history.

### Existing Streamlit review

An existing `manual_reviews` row is backfilled once to `journal_reviews` with
`source=legacy_backfill` and its original `updated_at`. The payload continues
reading the compatibility projection until a later versioned API/payload change.

### Attachment boundary

A future screenshot may produce metadata containing a private storage key,
filename, media type, size, and SHA-256. No file bytes or public URL enter
DuckDB, and no attachment field is published in the current dashboard payload.

## Validation and failure rules

- Empty identities, invalid enum values, non-positive revision numbers,
  negative attachment sizes, malformed hashes, and broken references fail
  before writing.
- Entry revisions are contiguous; a duplicate or skipped revision fails.
- A linked episode or strategy must exist when the link is created. A later
  episode rebuild never cascades deletion into journal records; a missing target
  is retained and reported as an orphaned-link reconciliation exception.
- Review supersession forms one chain per episode with one current head.
- Tag-event sequence numbers are contiguous and determine current membership.
- Journal text and attachment keys are excluded from ordinary logs and errors.
- Public/generated payload checks reject unapproved journal and attachment
  fields.
- No validation path writes to the runtime journal; tests use temporary DBs.

## Remaining approval boundaries

ADR-0008 and this contract are approved. Migration `0005`, transactional Save
Review dual-write, and temporary-database backfill validation are implemented.
Separate explicit approval is still required before:

- applying migration `0005` to the runtime journal database
- adding private journal narrative to a generated or unauthenticated payload
- choosing attachment storage, authorization, deletion, and retention policy
- enabling attachment upload, retrieval, preview, or deletion
