# ONJ-TRUST-06 roll lifecycle proof

This append-only package records the privacy-safe technical attestation for one bounded historical option roll. Exact broker identities, order and transaction records, contract details, quantities, fees, economics, isolated rehearsal database, and reproduction harness are retained in the external private evidence vault.

The isolated technical evidence path is **PASS**. The proof confirms the original option opening and close, replacement option opening, old/new contract relationship, quantity and position identity, premium/cost/fee reconciliation, realized-P&L boundary, and reproducible calculation fingerprints for this one lifecycle.

The project owner's bounded acceptance decision is recorded in
`public/owner-acceptance-v1-attestation.json`. The acceptance is append-only:
the technical attestation remains unchanged with `owner_sign_off: false` and
its pending status preserved as the historical state when it was written. The
public acceptance binds the private evidence lineage by hashes and omits
instrument, account, broker, and private-path identifiers.

The owner acceptance is limited to this one bounded diagonal option roll: the
original option open and close, replacement option open, roll relationship,
broker reconciliation, and realized-P&L boundary for the original lifecycle.
It does not establish replacement-contract closure, unrealized P&L, complete
broker-history coverage, other lifecycle transformations, portfolio-wide
financial correctness, production readiness, or authority for database,
migration, provider, commit, push, or trading actions.

Use or promotion of the proof currently fails closed because the private-vault
proof parent directory is `0755`; the required directory mode is `0700`.
The owner decision is recorded, but the evidence-use gate remains blocked
until that permission discrepancy is corrected and independently verified.

The technical assessment's historical owner-review status remains pending; the
separate append-only acceptance records the owner's bounded decision. This
proof does not establish complete broker-history coverage, general or
portfolio-wide financial correctness, replacement-contract closure, market
valuation, portfolio snapshots, exercise or other lifecycle transformations,
PNL-02 through PNL-08, production readiness, or authority for database,
migration, provider, commit, push, or trading actions.
