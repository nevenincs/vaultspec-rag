---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S17'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Make the watcher \_is_code_change preprocess-rule-aware (D8)

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

Made the watcher's `_is_code_change` preprocess-aware: it now takes an optional
`preprocess_config` and, after the vault/root checks, returns True for a file matched by a
preprocess rule even when its extension is not in `_CODE_EXTENSIONS` (D8). `watch_and_reindex`
resolves the config once at start via `code_indexer.preprocess_config()` (new public
accessor) and passes it to both the `watch_filter` and the per-change classifier.

## Outcome

A watched `.pdf` change now triggers a scoped reindex through the existing
debounce/cooldown/single-writer path; no other watcher logic changed.

## Notes

A rule added mid-session is picked up on the next service restart (documented limitation).
