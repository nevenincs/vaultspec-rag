---
tags:
  - '#exec'
  - '#index-lifecycle-consolidation'
date: '2026-07-25'
modified: '2026-08-14'
body_hash: 'sha256:1fe56745aa83f00c7a4f136b8c6f465dae10601d0c10f843d337c3bb07466671'
step_id: 'S04'
related:
  - "[[2026-07-25-index-lifecycle-consolidation-plan]]"
---

# Add the cross-indexer parity test binding every entry point to the shared lifecycle, and mutation-prove each guard can fail

## Scope

- `src/vaultspec_rag/tests/test_index_lifecycle.py`

## Description

Plan evidence: `2026-07-25-index-lifecycle-consolidation-plan` marks `S04` open for Add the cross-indexer parity test binding every entry point to the shared lifecycle, and mutation-prove each guard can fail.

## Outcome

The parity guard is delivered, in the existing lifecycle suite rather than the separate file the plan row named. `TestNoIndexerCarriesItsOwnCopy` in `src/vaultspec_rag/tests/test_index_lifecycle.py:380-476` carries all five guards:

- the enumeration guard, so an empty sweep cannot pass silently;
- the routing guard, binding every `full_index` / `incremental_index` the indexer package defines to the shared wrapper;
- the stamp guard, refusing a pasted-back activity-clock touch;
- the incremental-label guard, refusing a respelled mode ternary;
- the emitter guard, holding the index event namespace to the one module.

Entry points are discovered by enumerating the package, so a fourth content domain is caught by the test rather than remembered by its author. Twelve tests pass in the file.

A second test module was not created. The guards assert over the same shared lifecycle the behavioural tests in this file already drive, and splitting them would leave two suites naming one contract - the routing guard's docstring depends on the behavioural coverage sitting beside it to explain why a structural check is sufficient there and not elsewhere.

## Notes

Each of the five guards was driven both directions against `VaultIndexer`: rename `full_index`, call the locked body directly, paste a `touch_manifest_last_indexed` into the entry point, inline the mode ternary, and spell the event namespace at module scope. Every mutation landed on its own assertion and named exactly one indexer. Both directions are recorded in the class docstring, where the next reader of the guards will find them before loosening a matcher.
