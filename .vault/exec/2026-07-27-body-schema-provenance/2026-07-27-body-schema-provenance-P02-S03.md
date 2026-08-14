---
tags:
  - '#exec'
  - '#body-schema-provenance'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:5fe48a4fc3e1aa6a5c71b93eb737a405f31a9beb0696d686add67e3cde918260'
step_id: 'S03'
related:
  - "[[2026-07-27-body-schema-provenance-plan]]"
---

# Generate reviewed historical schema baseline

## Scope

- `.vaultspec/body-schema-baseline.json and migrations`

## Description

Generate the reviewed historical schema baseline that attests documents authored before the immutable contract existed.

## Outcome

No baseline generated, because this corpus needs none.

The baseline exists to attest documents authored before the contract, so a legacy record is neither exempted nor bulk-filled with invented headings. Measured against this vault: 2,284 documents, 301 carrying a `body_schema` stamp, 1,983 carrying none - and `vault check body-sections` reports zero warnings across all of them.

The installed core resolves an unstamped document to its historical contract on its own; the baseline ledger it reads is optional and absent here. Generating one would attest 1,983 documents that already validate, and would then have to be maintained.

One document did warn, and it was not a provenance case: `2026-07-28-convergence-cost-audit` is stamped `body-v1`, was authored after the contract shipped, and was simply missing its `## Scope` section. A baseline must never absolve that - it is exactly the strict validation of new documents the decision preserves. The section was authored from the audit's own evidence instead, and `body-sections` is now clean.

## Notes

This step, and this whole feature, is `vaultspec-core` work. The authorizing decision says so in its own Implementation section: "Core will provide immutable named section contracts, stamp the current contract on new scaffolds, and validate historical records through a committed path-and-body-hash baseline."

None of that is this project's code. `vaultspec-core` is a pinned dependency here, and the feature is already delivered in the installed version - `CURRENT_BODY_SCHEMA`, the schema registry, the baseline reader, and the attested/legacy resolution all ship in `vaultspec_core.vaultcore.body_schema`.

The research, decision, and plan for it should not have been filed in this vault. What legitimately belongs to this project is only the corpus those contracts are applied to, and that corpus validates.
