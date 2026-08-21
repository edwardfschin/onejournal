# ONJ-TRUST-01B evidence package

The original rehearsal is preserved under the ignored private bundle as
`v1-original`. Its technical evidence path passed, but it did not pass the
Trusted Ledger Exit Gate because Decimal-boundary conformance, lifecycle review,
and owner sign-off were still outstanding.

The privacy-safe attestations record exact fingerprints without publishing
account, instrument, trade, or P&L details. The Decimal-hardened reassessment is
preserved separately as `v2-decimal`; it does not replace `v1-original`. Its
technical evidence path passed and was subsequently accepted by the project
owner for that one bounded lifecycle in
`public/owner-acceptance-v1-attestation.json`. The acceptance is append-only:
the v1 and v2 attestations remain unchanged with `owner_sign_off: false` as
historical records of their state when written.

`partial-closure-preparation.json` records the privacy-safe selection state for
the next lifecycle. The candidate is selected and orders-to-transactions
reconciled, but no partial-closure P&L proof or owner acceptance is claimed. The
bounded owner acceptance above does not change that status.
