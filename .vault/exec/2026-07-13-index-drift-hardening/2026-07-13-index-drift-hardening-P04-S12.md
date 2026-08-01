---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:9e9f76959f14f1100bb6035621fa803f0d450fb22b44a500ba617458e4074d08'
step_id: 'S12'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Re-resolve the preprocess config when .vaultragpreprocess.toml changes by admitting it in the change filter for that purpose only, and add .md to the watcher code-extension set to match the indexer language map

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Add `.md` to the watcher `_CODE_EXTENSIONS` so non-vault markdown edits reach
  the indexer (the chunker language map already indexes markdown); vault
  classification still wins first in the change filter.
- Add a `_CONFIG_FILENAMES` set (`.gitignore`, `.vaultragignore`, the preprocess
  config filename) admitted by `_is_code_change` so index-shaping control-file
  edits reach the indexer as ordinary changed paths for the config-epoch check
  to observe and self-escalate.
- Re-resolve the watcher's preprocess config when the root
  `.vaultragpreprocess.toml` changes, holding it in a single-slot list the
  change filter closes over (satisfies the ruff loop-binding rule) and logging a
  `preprocess_config_reloaded` event with the new rule count.
- Add `test_watcher_unit.py`: six no-GPU tests covering control-file admission
  (root and nested), markdown inside/outside the vault, out-of-root rejection,
  and unrelated-extension rejection.

## Outcome

Ruff, ruff format, and basedpyright clean on both files; the six new unit tests
pass. The watcher now feeds every drift-relevant event to the indexer without
performing any drift classification of its own.

## Notes

Deviation from ADR D9, deliberate and widening-only: D9 admitted only the
preprocess config to the change filter, but an ignore-file edit with no
subsequent source change would then never trigger an incremental entry, so the
epoch check could not run. Admitting all three control filenames keeps the
watcher classification-free while guaranteeing the epoch check gets its entry.
The forwarded control-file path itself is inert inside the scoped reconcile
(not indexable, absent from prior metadata).
