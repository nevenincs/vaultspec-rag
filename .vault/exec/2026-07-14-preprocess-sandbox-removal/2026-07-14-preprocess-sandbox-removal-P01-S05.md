---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:57d4a3e824638483f8d9c8049299ef4f6e8dd7386df883cc09018c9325d1a32f'
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
