---
tags:
  - '#research'
  - '#preprocess-batch-hooks'
date: '2026-07-21'
modified: '2026-07-21'
related: []
---

# `preprocess-batch-hooks` research: `per-file hook spawn overhead and batch amortization`

## Findings

### The cost model (issue #241)

`run_preprocessor` (`src/vaultspec_rag/indexer/_preprocess_runner.py`) launches
one OS subprocess per (file, rule) invocation. The constant per-spawn cost
dominates for cheap hooks, and project-launcher commands multiply it.

Measured on the dev machine (2026-07-21, `bench_preproc.py`, median of 20):

| Shape                                  | Per-file cost | 1000 files |
| -------------------------------------- | ------------- | ---------- |
| bare `python -c` noop hook, spawn/file | 102.7 ms      | 103 s      |
| `uv run python` noop hook, spawn/file  | 217.3 ms      | 217 s      |
| one spawn handling 100 files (batch)   | 1.2 ms        | 1.2 s      |

Batching is an ~85-180x improvement for hooks whose real work is small
relative to interpreter/launcher startup. For heavy hooks (OCR, workbook
parse) the spawn constant matters less, but batching never hurts.

### What already bounds the pain

- The D7 content-hash cache (`_preprocess_cache.py`) makes unchanged files
  free on re-index; first index, clean rebuilds, and hook-version bumps
  re-pay full spawn cost.
- Both call sites (`chunk_file_with_status`, `chunk_and_hash_file` in
  `_chunk_worker.py`) execute inside the spawn process pool, so cross-file
  parallelism equals the pool size; parallelism divides but does not remove
  the per-file constant.

### Architectural constraints on a fix

- Workers are CPU-only (`index-workers-stay-cpu-only`); any batching must
  stay in the worker/pool layer and keep torch out of the import chain.
- The v1 hook contract (one path argument, JSON on stdout, `on_error`
  disposition, emitted-text caps, wall-clock timeout) is public; existing
  hooks must keep working unchanged.
- Trust model per the preprocess-sandbox-removal ADR: hooks are repo-authored
  code running with operator privileges; output/timeout bounds are the
  operating guards and must survive any batching design.
- Batching conflicts with per-file pool dispatch: matched files must be
  grouped per rule before dispatch, while unmatched files keep the existing
  per-file flow.

### Candidate directions

1. **Batch invocation (paths manifest per spawn)** - rule opts in
   (`batch = true`); the command receives a manifest file of N source paths
   and emits a JSON array of per-file outputs. Amortizes startup N-fold;
   contract delta is small; per-file cache/`on_error` semantics preserved by
   splitting the array result.
1. **Persistent hook worker** - hook runs once per (rule, index run) as a
   line-JSON stdin/stdout server. Best amortization but a much bigger
   contract (lifecycle, per-request timeouts, kill-on-wedge, restart
   policy); supersedes batching rather than complementing it.
1. **Guidance only** - document that hook commands should be direct
   executables, not `uv run`. Halves the constant at best; does not fix the
   class.

## Recommendation

Adopt direction 1 (opt-in batch manifest) now; leave direction 2 as a future
escalation if batch spawns remain hot. Decision details belong to the ADR.
