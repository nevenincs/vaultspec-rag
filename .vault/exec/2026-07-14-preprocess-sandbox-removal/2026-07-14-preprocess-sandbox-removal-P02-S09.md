---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S09'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Remove the --preprocess-unsandboxed flag and its mutual-exclusion validation from the index command

## Scope

- `src/vaultspec_rag/cli/_index.py`

## Description

- Remove `--preprocess-unsandboxed` and `_resolve_index_preprocess` (the mutual-exclusion validator) from the `index` command.
- Replace `_apply_preprocess_env` with `_apply_preprocess_off_env`; the delegation warning now speaks only for `--no-preprocess`.

## Outcome

`index --no-preprocess` still forces the kill switch for in-process runs; the removed flag is now an unknown-option error.

## Notes

None.
