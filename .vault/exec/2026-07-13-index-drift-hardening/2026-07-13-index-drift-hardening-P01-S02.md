---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S02'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Stamp membership and content epoch keys in \_write_meta, strip them in \_load_meta, and check both in \_incremental_index_locked before scoped dispatch: content mismatch escalates to \_full_index_locked(clean=True), membership mismatch forces the unscoped incremental, legacy sidecars without the keys trigger one unscoped reconcile

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add two reserved sidecar keys beside the embed-schema sentinel - a membership
  epoch and a content epoch - both prefixed with a double underscore so
  `_load_meta` strips them from file-path set arithmetic.
- Split the ignore-spec construction so the raw pattern lists are collectible
  without recompiling: a gitignore pattern collector (the single tree walk) and
  a file-only vaultragignore pattern collector that deliberately omits CLI
  `--exclude` entries so the epoch never thrashes between an ad-hoc CLI run and
  the resident service.
- Add `_resolve_scan_inputs` to resolve the compiled specs, the raw pattern
  lists, and the preprocess config in one gitignore rglob, and thread that
  result through `_scan_codebase`, `_scan_changed_paths`, and the scoped
  incremental so the watcher's hot path adds no second tree walk.
- Add the drift classifier and a dispatch helper that resolves inputs once at
  the incremental entry, stamps the run's epochs, and escalates before scoped
  dispatch: a content-epoch mismatch triggers a clean rebuild, a membership
  mismatch (or a legacy sidecar missing the keys) forces the unscoped
  incremental, and an unchanged config proceeds untouched.
- Stamp both epochs in `_write_meta` from the run's resolved inputs, with a
  guarded recompute fallback that only fires when the instance carries a root
  and omits the keys otherwise so partially-constructed test instances are
  unaffected.

## Outcome

Every incremental entry - watcher, CLI, and MCP scoped callers alike -
self-heals against index-shaping config drift under the already-held writer
lock, reusing the proven embed-schema escalation precedent. The scoped path
walks the tree exactly once per run: `_resolve_scan_inputs` performs the sole
gitignore rglob and the scoped scan consumes its compiled specs. The full unit
suite and the targeted-reindex and codebase GPU integration suites pass with no
spurious rebuilds - scoped runs stay scoped when the config is unchanged.

## Notes

The membership-versus-content precedence is intentional: content drift outranks
membership drift because the clean rebuild subsumes the membership reconcile. A
legacy sidecar (pre-feature, missing both keys) is reconciled by a single
unscoped incremental rather than a clean rebuild, matching the accepted
decision; the unscoped run then stamps fresh epochs so subsequent runs classify
precisely.
