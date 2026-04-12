---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-1-progress-module`

Add the `ProgressReporter` Protocol with `NullProgressReporter` no-op and
`RichProgressReporter` TTY-aware adapter; unit tests cover no-op behaviour,
line-based fallback output, and threaded counter correctness.

- Created: `src/vaultspec_rag/progress.py`
- Created: `src/vaultspec_rag/tests/test_progress_unit.py`

## Description

The new `progress` module defines a runtime-checkable `typing.Protocol`
with `phase_start`, `advance`, `phase_end`, and `log` methods. The Rich
adapter owns a lazily-created `rich.progress.Progress` with spinner,
description, bar, M-of-N counter, and elapsed-time columns; on
construction it consults `console.is_terminal` and routes to either the
live-bar path or a line-based fallback that prints `==> {name}` / `done`
markers. The fallback counter is guarded by `threading.Lock` so worker
threads in the indexer parse phase can advance it safely. The adapter
also implements `__enter__` / `__exit__` so the CLI can use it as a
context manager (live Progress is only started in TTY mode).

Rich imports are lifted out of the `TYPE_CHECKING` block where possible
to keep the module import-safe without polluting indexer-side type
annotations. The `NullProgressReporter` consumes its arguments via `del`
statements to satisfy `ruff ARG002` without adding `# noqa` (the project
forbids lint suppressions).

## Tests

`src/vaultspec_rag/tests/test_progress_unit.py` covers:

- `NullProgressReporter` satisfies `isinstance(..., ProgressReporter)`
  and accepts every method call without error.
- `RichProgressReporter` in line-based mode emits the expected `==>`
  header and `done` trailer, including zero-total and unknown-total
  variants.
- A `ThreadPoolExecutor(max_workers=16)` hammer submits 1000
  `advance(1)` calls; the internal counter equals exactly 1000.
- `log` routing in both live and fallback modes.
- Context-manager lifecycle in non-TTY mode.

Verification: `uv run --active ruff check src/vaultspec_rag/` passes,
`uv run --active ruff format --check` passes, and
`uv run --active pytest src/vaultspec_rag/tests/test_progress_unit.py -q`
reports 12 passed.
