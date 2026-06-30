---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a manifest read and reverse-map helper resolving a collection prefix to its root

## Scope

- `src/vaultspec_rag/registry.py`

## Description

- Add `load_manifest` returning a prefix-to-entry mapping, tolerant of a missing or corrupt manifest (treated as empty so the conservative outcome is every namespace classified unknown).
- Add `reverse_map(prefix)` resolving a collection prefix back to its root path, or `None` when unattributable.
- Add `classify_root(entry)` returning live or orphaned by checking whether the recorded root still exists, plus `record_root`, `remove_root`, and `remove_prefix`.

## Outcome

Read and reverse-map helpers implemented and unit-tested: 9 unit tests pass (round-trip, prefix parity with `root_collection_prefix`, reverse-map known/unknown, preserve-other-entries, remove, live-then-orphaned classification, missing/corrupt tolerance). ruff, ruff format, and basedpyright clean.

## Notes

JSON parsing is typed strictly (parse to `object`, narrow with `isinstance`, `cast` to `dict[str, object]`) to satisfy the gating basedpyright with no suppressions. Same dedicated-module placement as S06.
