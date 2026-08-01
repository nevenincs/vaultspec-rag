---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:6a7317467c081c479b5505e5147b3d3ee3ce2f60b091f35a6f0944a4cbde8fee'
step_id: 'S07'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_store_search.py`

## Description

- Introduce immutable hybrid-search request and internal execution values.
- Migrate the production searcher and all direct real tests.
- Verify the store and search behavior through focused real suites.

## Outcome

All hybrid-search entry points now receive one cohesive request value; the remaining
searcher complexity is separately tracked by its own plan row.

## Notes

Ninety focused store and search tests passed with expected operational warnings.
