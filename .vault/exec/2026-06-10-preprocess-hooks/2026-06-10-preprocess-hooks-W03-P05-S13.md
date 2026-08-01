---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:2ec235e425d64c29ed3203bf0f4435b43975babd35b0d07e94ea4e0f34bcb87e'
step_id: 'S13'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Thread resolved rules and knobs pickle-safely from the codebase indexer into the worker calls (D6)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Made `PreprocessConfig` picklable via `__reduce__` (rebuilds matchers from the picklable
rules on unpickle) and added a frozen `PreprocessContext` (config + cache_root +
max_emitted_bytes). The indexer resolves it once per run via `_resolve_preprocess_context()`
(returns `None` when no rules, keeping the worker path byte-identical), stores it on
`self._prep_ctx` in `_begin_preprocess_run()`, and threads it into every worker submission
(`_chunk_paths`, `_chunk_paths_serial`, `_run_serial_chunk_and_embed`, `_drain_pool`,
`_process_future`) (D6).

## Outcome

Context crosses the spawn boundary pickle-safely (test_preprocess_worker); zero overhead
when no rules are configured.

## Notes

Runs are serialised by `_writer_lock`, so per-run instance state is safe.
