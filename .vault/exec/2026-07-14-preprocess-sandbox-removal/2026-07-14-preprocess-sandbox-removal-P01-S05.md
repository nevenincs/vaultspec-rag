---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S05'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Drop the server_mode/unsandboxed threading from preprocess_file and its callers, keeping the cache consult/write path unchanged

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Drop the `server_mode`/`unsandboxed` threading from `preprocess_file`'s `run_preprocessor` call; cache consult/write path untouched.

## Outcome

Worker passes only `max_emitted_bytes` and `project_root`.

## Notes

None.
