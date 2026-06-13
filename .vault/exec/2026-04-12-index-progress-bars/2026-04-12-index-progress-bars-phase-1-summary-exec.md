---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
  - '[[2026-04-12-index-progress-bars-adr]]'
---

# `index-progress-bars` `phase-1` summary

Phase 1 delivers the full `ProgressReporter` contract end-to-end:
a new `progress` module with a Null no-op and a TTY-aware Rich adapter;
re-implemented vault and codebase indexer entry points that require
`reporter` and emit granular phase events around every pipeline step;
a CLI rewrite that drives init sub-steps and both indexers through a
single reporter; lockstep updates at every in-tree call site; and
progress-specific unit plus real-GPU integration coverage.

- Created: `src/vaultspec_rag/progress.py`
- Created: `src/vaultspec_rag/tests/test_progress_unit.py`
- Created: `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-1-progress-module.md`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-2-vault-indexer.md`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-3-codebase-indexer.md`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-4-cli-rewrite.md`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-5-call-sites.md`
- Created: `.vault/exec/2026-04-12-index-progress-bars/2026-04-12-index-progress-bars-phase-1-task-6-progress-tests.md`
- Modified: `src/vaultspec_rag/indexer.py`
- Modified: `src/vaultspec_rag/cli.py`
- Modified: `src/vaultspec_rag/api.py`
- Modified: `src/vaultspec_rag/mcp_server.py`
- Modified: `src/vaultspec_rag/watcher.py`
- Modified: `src/vaultspec_rag/tests/conftest.py`
- Modified: `src/vaultspec_rag/tests/integration/conftest.py`
- Modified: `src/vaultspec_rag/tests/integration/test_api_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_codebase_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_indexer_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_performance.py`
- Modified: `src/vaultspec_rag/tests/test_service_registry.py`
- Modified: `src/vaultspec_rag/tests/benchmarks/bench_rag.py`

## Description

The new `progress` module owns a runtime-checkable `typing.Protocol`
with four methods (`phase_start`, `advance`, `phase_end`, `log`). The
`NullProgressReporter` is the canonical silent backend. The
`RichProgressReporter` lazily creates a `rich.progress.Progress` with
spinner, description, bar, M-of-N counter, and elapsed-time columns;
in non-TTY mode it downgrades to plain `==>` / `done` lines and guards
its fallback counter with a `threading.Lock` so worker threads in the
indexer parse phase can advance it concurrently.

The vault and codebase indexer entry points are re-implemented with
`reporter` as a required keyword-only argument — no defaults, no
shims. Phase events wrap every pipeline step; the embed phase is
sliced into sub-batches sized against the existing
`embedding_batch_size` so the reporter can fire per-document advance
events between GPU calls. Dense and sparse embeddings each own their
own phase. Zero-work shortcuts still emit empty `phase_start`/
`phase_end` pairs so the UI never falls silent.

The CLI rewrite replaces the old three-task coarse `rich.Progress`
with a single `RichProgressReporter` used as a context manager.
Init sub-steps each drive their own phase explicitly, and both
indexers then feed the same reporter. The final summary table is
preserved; dry-run and MCP-delegation branches return before the
reporter is constructed.

Every in-tree call site of `full_index` / `incremental_index` was
updated in lockstep. `api.py` keeps an optional `reporter` parameter
on its public facade (per the ADR), internally defaulting to
`NullProgressReporter`. `mcp_server.py`, `watcher.py`, and every test
fixture thread a `NullProgressReporter` explicitly. `indexer.py` and
`embeddings.py` contain zero references to `rich` (verified by grep).

Phase-6 coverage adds a 12-test `test_progress_unit.py` (Null no-op,
line-fallback output, threaded counter hammer, context-manager
lifecycle, protocol compliance) and a real-GPU
`test_indexer_progress_integration.py` that drives both indexers
against fresh synthetic corpora and asserts phase order, balanced
start/end pairs, and per-phase advance totals against the resulting
corpus size. No mocks, no skips.

## Tests

Verification commands:

- `uv run --active ruff check src/vaultspec_rag/` — all checks passed.
- `uv run --active ruff format --check src/vaultspec_rag/` — 51 files
  already formatted.
- `uv run --active pytest src/vaultspec_rag/tests/ --ignore=src/vaultspec_rag/tests/integration --ignore=src/vaultspec_rag/tests/benchmarks` —
  329 passed (32 deselected: pre-existing GPU-gated fixtures in
  `test_service_registry.py` and `test_store_codebase.py` that
  require a real `HF_TOKEN`; unchanged by this phase).
- Integration tests require real GPU + `HF_TOKEN` and are gated at
  collection time by the repo-level conftest; a manual TTY run of
  `vaultspec-rag index` against a real vault is required before merge
  per the plan verification criteria.
