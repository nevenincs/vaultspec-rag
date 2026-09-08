---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:d871fc0277b6b81dce85df3947cfc53c039f3c5291d2573fbfd26adb6ea45668'
step_id: 'S07'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Mutation-prove exact source and root matching plus bounded evidence

## Scope

- `src/vaultspec_rag/tests/test_search_availability.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_search_availability.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P02-S07.md`
- `verify:` `uv run --no-sync pytest 'src/vaultspec_rag/tests/test_search_availability.py::test_legacy_and_invalid_canonical_identity_are_rejected' -q --tb=short` -> `pass`
- `verify:` `uv run --no-sync pytest 'src/vaultspec_rag/tests/test_search_availability.py::test_projection_and_legacy_job_evidence_share_one_bound' -q --tb=short` -> `pass`
