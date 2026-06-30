---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S46'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add an out-of-process entry-point runner that imports module:callable and emits PreprocOutput JSON (D9 follow-up)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_entry.py`

## Description

Added `_preprocess_entry.py`: a `python -m` runnable that resolves a `"module:callable"`
reference (`resolve_entry_point`), calls it with the source path, and emits the returned
mapping/pydantic model as one JSON document on stdout - the same contract a `command`
satisfies. Distinct non-zero exit codes for bad-ref / raise / non-JSON so the runner maps
each to a per-file skip.

## Outcome

Module complete; the entry_point form runs out-of-process, so CPU-only isolation and
timeout hold by construction (the safe form of D9).

## Notes

This realises the codification candidate `preprocessors-run-out-of-process`.
