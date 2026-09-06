-- Migration 0017: local-owner journal API audit and idempotency receipts.
--
-- This migration records only operation metadata, stable resource identities,
-- and request hashes. It must never store journal entry bodies, review notes,
-- account identifiers, raw evidence paths, credentials, or provider payloads.
--
-- Runtime application remains an explicit operator action. Applying this
-- migration to a private journal database requires the normal backup and
-- approval workflow; tests use temporary databases only.

CREATE TABLE local_owner_api_audit_events (
    audit_event_uid UUID PRIMARY KEY DEFAULT (uuid()),
    operation_uid VARCHAR,
    action VARCHAR NOT NULL,
    resource_type VARCHAR NOT NULL,
    resource_uid VARCHAR,
    outcome VARCHAR NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    CHECK (action IN (
        'journal_search', 'review_queue_read', 'trade_lifecycle_read',
        'journal_entry_read', 'journal_review_write', 'journal_entry_write',
        'journal_entry_revision_write'
    )),
    CHECK (outcome IN ('accepted', 'replayed', 'rejected')),
    CHECK (length(request_sha256) = 64),
    CHECK (request_sha256 = lower(request_sha256))
);

CREATE INDEX idx_local_owner_api_audit_occurred_at
  ON local_owner_api_audit_events (occurred_at);

CREATE TABLE local_owner_api_operation_receipts (
    operation_uid VARCHAR PRIMARY KEY,
    action VARCHAR NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    resource_type VARCHAR NOT NULL,
    resource_uid VARCHAR NOT NULL,
    revision_no INTEGER,
    created_at TIMESTAMP NOT NULL,
    CHECK (action IN ('journal_review_write', 'journal_entry_write', 'journal_entry_revision_write')),
    CHECK (length(request_sha256) = 64),
    CHECK (request_sha256 = lower(request_sha256)),
    CHECK (revision_no IS NULL OR revision_no > 0)
);
