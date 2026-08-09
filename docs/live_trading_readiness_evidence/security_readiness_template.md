# LIV-01 Security Readiness Template

Owner: Project owner

Date created: 2026-08-09

This file is a structured evidence pack placeholder for `LIV-01-2 (Security)`.
Evidence ID: `EVID-LIV-01-02`

## Required evidence

- [x] Environment boundaries approved (dev/test/staging/paper/live)
- [x] Secret handling policy documented (rotation, storage, access control)
- [x] Secret rotation and emergency response workflow documented
- [x] Access logging and anomaly alerting controls specified
- [x] Runtime paths with secrets excluded from tracked/generated outputs

## Evidence fields

- Approved secret store and IAM policy: Secrets are environment-bound and injected at runtime; not committed in source, scripts, or DB artifacts.
- Environment separation plan: dev/test sandbox in repository; paper/live broker write paths intentionally not enabled in this branch.
- Rotation and revocation process: operator rotates local tokens as part of session management and must revoke immediately on suspected leak.
- Audit log retention policy: execution and import logs are retained in evidence files and local audit history with sensitive values redacted.
- Approver(s): Project owner
- Review date (UTC): 2026-08-09
- Notes and constraints: Security posture is provisional and repository-local; external security review and hardening remain required before live deployment.
