# ONJ-GOV-04 Change Impact Checklist

## Purpose

This checklist controls the governance-only remediation approved for
ONJ-GOV-04A. It prevents an ADR status or scope change from being applied to
only one document while dependent governance claims remain stale.

This work changes documentation and governance validation only. It does not
change runtime behavior, databases, released migrations, broker/provider
configuration, generated output, deployment state, or operational acceptance.

This checklist preserves the ONJ-GOV-04A checkpoint before the project owner's
2026-08-21 ADR-0003 confirmation. The accepted ADR and architecture register
are authoritative for the subsequent status.

## Entry gate

- [x] Confirm the checkout and branch before editing.
- [x] Preserve the pre-existing `AGENTS.md` change without editing it.
- [x] Record the affected authority, consumers, validation, and rollback path.
- [x] Keep runtime code, databases, migrations, provider configuration, and
  generated output out of scope.

## Impact map

| Area | Authoritative change | Downstream consumers | Persisted/runtime impact | Validation | Rollback |
|---|---|---|---|---|---|
| ADR-0003 | Correct the invalid status to `Proposed`, refresh factual implementation context, and record seven pending owner decisions | Architecture register, CON-02, P&L acceptance language, data contract, maturity claims | None | ADR/register consistency, decision checklist review, reference scan | Revert factual wording errors; do not restore the unsupported `Approved` status |
| ADR-0006 and ADR-0010 | Accept only the implemented identity/replay and calculation-fingerprint foundation; move full provenance and correction governance to proposed ADR-0010 | Architecture register, CON-05/CON-07, JRN-06/JRN-08, normalized-fill and import-audit contracts, strategy mapping, maturity map | None in this tranche; ADR-0010 implementation may later require additive migrations | ADR/register consistency, identity/fingerprint focused tests, reference scan | Material changes to accepted ADR-0006 require supersession; ADR-0010 remains independently reversible while proposed |
| ADR-0007 | Accept the fail-closed policy while recording explicit implementation, validation, accessibility, operational, and financial non-claims | Architecture register, CON-06, PNL-02/03/04/08, dashboard/data contracts, maturity map | None | ADR/register consistency, dashboard limitation review, reference scan | A material policy change requires a superseding ADR; later payload work remains versioned separately |
| Roadmap and strategic documents | Separate policy acceptance, implementation, validation, and operational acceptance | Delivery sequence, capability maturity, spreadsheet evolution mapping | None | Cross-document status and terminology checks | Revert this governance change as one coherent set rather than leaving partial cross-references |

## ADR-0003

- [x] ADR file status and factual implementation context updated.
- [x] Seven policy areas recorded as pending project-owner confirmations.
- [x] Architecture register aligned.
- [x] CON-02 blocked without discarding existing implementation evidence.
- [x] Current contract dependencies state that financial acceptance cannot rely
  on unresolved ADR-0003 semantics.
- [x] Migrations 0009 and 0010 historical wording documented without editing
  either checksum-locked migration.

## ADR-0006 and ADR-0010

- [x] ADR-0006 narrowed to the implemented identity/replay and calculation-
  fingerprint foundation and accepted only within that scope.
- [x] Proposed ADR-0010 records the unimplemented provenance, supersession,
  correction-governance, invalidation, recalculation, privacy, retention, and
  recovery decisions.
- [x] Architecture register aligned with both ADRs.
- [x] CON-05 narrowed; CON-07 added for the proposed broader policy.
- [x] JRN-06 narrowed; JRN-08 added for durable correction/provenance work.
- [x] Normalized-fill replay terminology matches the implemented normalized-
  economic signature rather than claiming byte-identical evidence replay.
- [x] Import-run audit scope is identified as batch lineage, not complete
  evidence provenance.
- [x] Strategy mapping and maturity claims split the validated identity
  foundation from M0 broader correction/provenance capability.

## ADR-0007

- [x] ADR-0007 records the approved Option A policy and explicit non-claims.
- [x] Architecture register aligned.
- [x] CON-06 completion evidence states policy acceptance, not implementation
  completion.
- [x] PNL-02 remains in progress; PNL-03, PNL-04, and PNL-08 remain blocked.
- [x] PNL-08 lists false-valid, false-zero, missing count/reason, responsive,
  and accessibility gaps.
- [x] Dashboard and data contracts identify current payload conformance as
  incomplete without adding unimplemented required fields.

## Validation and no-impact review

- [x] Governance validation rejects unsupported ADR statuses and register/file
  status mismatches.
- [x] All ADR links resolve and all registered ADR statuses match their files.
- [x] Roadmap and strategic references tell one consistent scope/status story.
- [x] Whitespace and complete diff checks pass.
- [x] `AGENTS.md` and released migration hashes remain unchanged from the entry
  snapshot.
- [x] Product vision and root README require no semantic change because their
  high-level product and authority boundaries remain accurate.
- [x] No runtime code, database, released migration, provider configuration,
  generated output, commit, push, or remote operation occurred.
