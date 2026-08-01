---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:54d303b254bb1f257448755e8a1ab9cb5b98113c8c12b8ffa0687cc48eb2ee87'
step_id: 'S37'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add incremental and watcher routing coverage for a preprocessable change (D8)

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

Added an incremental test that full-indexes, writes a new `appendix.pdf`, then calls
`incremental_index(changed_paths=[new_pdf])` - exactly the scoped entrypoint the watcher
invokes on a change - and asserts the new binary was extracted and added (D8).

## Outcome

Passes; confirms the scoped/watcher path routes a changed binary through the preprocessor
and the preprocess-aware gate admits it.

## Notes

Exercises the gate-awareness + worker integration on the incremental path, not just full
index.
