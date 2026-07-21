---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S04'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Rewire run_preprocessor to launch the hook directly against the original source path with a fresh scratch cwd, dropping backend resolution/memos, staging, \_remap_staged_paths, the \_REFUSED_REASON policy, and the server_mode/unsandboxed parameters while keeping timeout, stdout/stderr caps, schema validation, the emitted cap, on_error dispositions, and argv hygiene

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Rewire `run_preprocessor` to launch the hook directly against the original source path via `default_popen_handle`.
- Drop backend resolution and the per-worker backend memos, staging, `_remap_staged_paths`, and the fail-closed refusal reason.
- Drop the `server_mode`/`unsandboxed` parameters.
- Keep the wall-clock timeout, stdout/stderr caps, schema validation, emitted-text cap, `on_error` dispositions, and argv hygiene unchanged.
- Child cwd is a fresh `mkdtemp` scratch dir removed in a `finally`.

## Outcome

Per-file hook cost is one bare process spawn; all bounds preserved.

## Notes

None.
