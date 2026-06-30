---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S39'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Implement a service-domain migrate that relocates and converts a root index between local and server backends using the selected tooling

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Add migrate_collections: name-mapped copy (bare \<-> r{hash}\_) recreating named dense+sparse schema from source, scroll+upload, count-verified; skip existing target / missing source.

## Outcome

Typed MigrateResult; covered by the remap-copy integration test. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
