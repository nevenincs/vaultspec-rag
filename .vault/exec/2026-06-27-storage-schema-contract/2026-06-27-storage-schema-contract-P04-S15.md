---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:bc42e602cb2a7738a6993f4e0ab6f8a8dd8e33f15a4ad957772290073b7cb85a'
step_id: 'S15'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Author the storage-schema reference document with the field tables, version-bump policy, and consumer compatibility recipe

## Scope

- `.vault/reference/2026-06-27-storage-schema-contract-reference.md`

## Description

- Scaffolded the reference via `vaultspec-core vault add reference` and authored the contract body: collection/namespacing, the vector table, the per-collection payload field lists, the server-mode payload indexes, the point-ID schemes, the version-bump policy, the runtime advertisement surfaces, the consumer compatibility recipe, the clean-reindex recovery, and the source/test map.
- Named `store_schema.py` as the single source of truth and the four test files that hold the guarantees.

## Outcome

The dashboard team (and any future direct-Qdrant consumer) has a machine-facing contract to build against, with the version-bump policy and the assert-before-read recipe spelled out.

## Notes

Authored, not generated (ADR D5); a generated-from-the-typed-definition reference is recorded as a possible later hardening.
