-- Operator executes each section in its own database after schema/provisioning
-- or a fresh restore. Create non-owner LOGIN roles separately, with private
-- generated passwords. Do not grant either role to the OneBot identity.
-- Journal database section (role: onejournal_app)
GRANT CONNECT ON DATABASE onejournal_journal TO onejournal_app;
GRANT USAGE ON SCHEMA main TO onejournal_app;
GRANT SELECT ON ALL TABLES IN SCHEMA main TO onejournal_app;
GRANT INSERT ON main.journal_entries, main.journal_entry_revisions,
    main.journal_reviews, main.manual_reviews,
    main.local_owner_api_operation_receipts, main.local_owner_api_audit_events,
    main.local_owner_financial_api_audit_events, main.phase1_reporting_api_audit_events
    TO onejournal_app;
GRANT UPDATE ON main.manual_reviews TO onejournal_app;

-- Security database section (role: onejournal_access)
GRANT CONNECT ON DATABASE onejournal_security TO onejournal_access;
GRANT USAGE ON SCHEMA main TO onejournal_access;
GRANT SELECT ON ALL TABLES IN SCHEMA main TO onejournal_access;
GRANT INSERT ON main.passkeys, main.access_failures, main.access_audit, main.access_denial_counts TO onejournal_access;
GRANT UPDATE ON main.access_meta, main.passkeys, main.access_denial_counts TO onejournal_access;
GRANT DELETE ON main.access_failures TO onejournal_access;
-- Runtime receives no CREATE, financial-write, revision-update/delete, audit-
-- delete, role-management or database-owner privilege. Recovery uses an offline
-- operator, not these runtime roles. New migrations require reviewed grants.
