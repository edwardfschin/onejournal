-- Migration 0022: privacy-safe broker-current financial API read audit.
--
-- This table is additive and deliberately separate from the WEB-W06 journal
-- audit action constraint. It records the exact accepted valuation and owner
-- authorization identities released by the loopback API, but no account ID,
-- instrument identity, financial value, raw path, credential, or provider
-- payload.
--
-- Applying this migration to an operational journal remains subject to the
-- normal backup, rehearsal, validation, and explicit approval workflow.

CREATE TABLE local_owner_financial_api_audit_events (
    audit_event_uid UUID PRIMARY KEY DEFAULT (uuid()),
    action VARCHAR NOT NULL,
    valuation_run_uid VARCHAR NOT NULL,
    result_fingerprint VARCHAR(64) NOT NULL,
    owner_acceptance_uid VARCHAR NOT NULL,
    outcome VARCHAR NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    CHECK (action = 'broker_current_portfolio_read'),
    CHECK (outcome = 'accepted'),
    CHECK (length(result_fingerprint) = 64),
    CHECK (result_fingerprint = lower(result_fingerprint)),
    CHECK (length(request_sha256) = 64),
    CHECK (request_sha256 = lower(request_sha256))
);

CREATE INDEX idx_local_owner_financial_api_audit_occurred_at
  ON local_owner_financial_api_audit_events (occurred_at);
