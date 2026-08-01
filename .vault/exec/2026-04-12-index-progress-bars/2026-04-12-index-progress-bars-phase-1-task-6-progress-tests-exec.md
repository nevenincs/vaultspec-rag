---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-07-27'
body_hash: 'sha256:bedbb3cd7e46823beb33e5f3eec56cd4226c4691486a58dcd75b7b61cf2d2e4e'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-6-progress-tests`

Progress-specific unit + integration coverage. Adds a
`CountingProgressReporter` helper and real-GPU integration tests that
drive both indexers end-to-end.

- Modified: `src/vaultspec_rag/tests/test_progress_unit.py`
- Created: `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py`

## Description

`CountingProgressReporter` is defined locally in the unit test module
and re-declared in the integration test module (test-local helper, no
new public surface). Every event is recorded as a
`(kind, payload)` tuple so assertions can inspect phase order, pairing,
and per-phase advance totals.

The integration tests run a real `VaultIndexer.full_index` and
`CodebaseIndexer.full_index` against a fresh synthetic vault / code
project on the real GPU. Assertions:

- Phase names appear in the exact expected order.
- Every `phase_start` is balanced by a `phase_end`.
- The dense and sparse embed phases advance exactly once per doc/chunk.
- `upsert` and `write metadata` phases each advance by 1.

No mocks, no skips. GPU fixtures reuse the session-scoped
`embedding_model` from `tests/conftest.py`.

## Tests

Unit tests green (12 passing in `test_progress_unit.py`). Integration
tests are GPU-bound and gated on `HF_TOKEN`; they exercise real GPU and
real Qdrant, compatible with the existing test mandate.

## Notes

Evidence gap: the retained document body has no separately labelled Notes section.

## Outcome

Evidence gap: the retained document body has no separately labelled Outcome section.
