---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:bb292c3cc83868e7c4e542258612594df0e0f6d3a8fb27b1bd5a550c565ee921'
step_id: 'S09'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Implement the preprocess cache: key composition, sharded per-source JSON, atomic tmp-plus-replace write (D7)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_cache.py`

## Description

Added `_preprocess_cache.py`: content-addressed cache of successful outputs under
`<data_dir>/preprocess-cache/<shard>/<key>.json`. The key is
`blake2b(source_hash | command | schema_version)`; `read_cached_output` returns the
re-validated `PreprocOutput` on a hit and treats any corrupt/collided entry as a miss;
`write_cached_output` writes atomically (tmp + `os.replace`) and swallows write errors (the
cache is an optimisation, never a correctness dependency). Only `ok` results are cached, so
transient failures retry (D7).

## Outcome

Module complete; ruff + basedpyright zero. Per-source sharded files avoid a manifest
bottleneck across parallel workers.

## Notes

Command is the project's invalidation lever; source-hash is the dominant signal.
