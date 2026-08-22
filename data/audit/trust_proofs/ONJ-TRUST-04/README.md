# ONJ-TRUST-04 assignment proof

This append-only package records the privacy-safe technical attestation for one
bounded historical short-put assignment lifecycle. Exact broker identities,
instrument details, dates, economics, source records, approved lifecycle
instruction, and reproduction harness are retained in the external private
evidence vault.

The isolated technical evidence path is **PASS**. The proof confirms the short
option opening, manually reviewed broker assignment classification, successor
underlying creation, option-basis transfer, realized/unrealized boundary,
subsequent successor closure, broker reconciliation, and deterministic
fingerprints for this one lifecycle.

The project owner's bounded acceptance decision is recorded in
`public/owner-acceptance-v1-attestation.json`. The acceptance is append-only:
the technical attestation remains unchanged with `owner_sign_off: false` and its
pending status preserved as the historical state when it was written. To honor
the repository privacy contract, the public acceptance records the SHA-256 of
the exact owner statement instead of publishing the statement's instrument
identifier.

Use or promotion of the proof as accepted evidence currently fails closed. The
private-vault proof directory does not meet the required `0700` directory mode.
The owner decision remains recorded, but a separate append-only validation
closure is required after the permission discrepancy is corrected and verified.

The owner acceptance does not establish complete Schwab history coverage, all
assignment scenarios, general or portfolio-wide financial correctness, market
valuation, portfolio snapshots, exercise or roll handling, PNL-01 or downstream
roadmap status, production readiness, or authority for any database, migration,
provider, production, commit, push, or trading action. All recorded technical
limitations remain in force.
