---
tags:
  - '#plan'
  - '#index-progress-bars'
date: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-adr]]'
  - '[[2026-04-12-index-progress-bars-reference]]'
  - '[[2026-04-12-index-progress-bars-research]]'
---

# `index-progress-bars` `phase-1` plan

Straight re-implementation of the `vaultspec-rag index` progress-reporting
surface so every pipeline phase emits visible, granular feedback — with a
per-document progress bar driving the long embed phase — without coupling
the indexer or embeddings modules to Rich. Grounded in the accepted ADR and
the reference audit linked above.

## Proposed Changes

The accepted ADR commits to a `ProgressReporter` Protocol owned by a new
`src/vaultspec_rag/progress.py` module, with a Null implementation for
silent callers and a TTY-aware Rich adapter driven exclusively from the
CLI. The indexer entry points are re-implemented to take `reporter` as a
**required** keyword argument — no default, no shim, no deprecation path.
Every in-tree call site is updated in the same change.

The embed phase is sliced at the indexer layer (not inside `embeddings.py`)
into sub-batches so the reporter can fire per-document advance events
between slices. Multi-corpus UX is one `rich.Progress` with stacked task
rows covering init sub-steps plus vault and codebase phases, sequential to
match the existing orchestration. Non-TTY stdout triggers a line-based
fallback guarded by a `threading.Lock` counter. No new dependencies, no
new CLI flags, no change to indexing semantics or batch sizes beyond the
unavoidable slicing overhead.

## Tasks

- `Phase 1 — progress module`

  1. Add `src/vaultspec_rag/progress.py` containing the
     `ProgressReporter` Protocol (`phase_start`, `advance`, `phase_end`,
     `log`), the `NullProgressReporter` no-op class, and the
     `RichProgressReporter` adapter. The Rich adapter owns a
     `rich.Progress` instance, tracks the active task id, honours
     `console.is_terminal` to route between the live-bar branch and the
     line-based fallback branch, and guards its fallback counter with
     `threading.Lock`.
  1. Expose the module via `src/vaultspec_rag/__init__.py` if the package
     re-exports other public surfaces (verify first; do not add new
     exports gratuitously).
  1. Unit test scaffolding at `src/vaultspec_rag/tests/test_progress_unit.py`
     covering Null no-op behaviour, line-based fallback output (capture
     via `io.StringIO` Console target), and a threaded `ThreadPoolExecutor`
     hammer test asserting total counter correctness under contention.
     No mocks, no skips.

- `Phase 2 — VaultIndexer re-implementation`

  1. Re-implement `VaultIndexer.full_index` in `src/vaultspec_rag/indexer.py`
     to take `reporter: ProgressReporter` as a required keyword argument.
     Emit `phase_start`/`advance`/`phase_end` around: vault scan, per-doc
     hash, threaded parse consumer, sub-batched embed loop, store upsert,
     and metadata write. The embed phase replaces the single
     `encode_documents` call with a loop over slices of size
     `progress_batch_size` (sourced from config, defaulting to the
     existing dense batch size) and advances the reporter per slice.
     Sparse encoding is sliced the same way.
  1. Re-implement `VaultIndexer.incremental_index` with the same reporter
     contract. The hash-diff loop, parse consumer, embed loop, upsert,
     delete, and metadata write each emit phase events. Zero-work
     shortcuts still emit `phase_start(total=0)` + `phase_end` so the UI
     shows "nothing to do" rather than falling silent.
  1. Update `VaultIndexer` docstrings to document the new required
     parameter. No default, no backwards-compatible overload.

- `Phase 3 — CodebaseIndexer re-implementation`

  1. Re-implement `CodebaseIndexer.full_index` with the same reporter
     contract. Phase labels reflect the unit of work: "scan", "hash",
     "chunk", "embed", "upsert", "write-meta". The embed phase totals
     against chunk count (not file count) because that is the actual
     work unit downstream. Sliced embed loop mirrors `VaultIndexer`.
  1. Re-implement `CodebaseIndexer.incremental_index` analogously, with
     the same zero-work emit-empty-phase discipline.
  1. Verify via grep that no code path inside either indexer touches
     `rich` directly; all Rich usage must stay on the CLI side.

- `Phase 4 — CLI handle_index rewrite`

  1. In `src/vaultspec_rag/cli.py`, rewrite `handle_index` to construct a
     single `RichProgressReporter` wrapping a `rich.Progress` with
     spinner, description, bar, `MofNCompleteColumn`, and
     `TimeElapsedColumn`. The coarse three-task Progress is removed.
  1. Drive init sub-steps through the reporter: workspace resolve, config
     load, dense model load, sparse model load, reranker load, store
     open. Each gets its own `phase_start`/`phase_end` pair. The
     existing "Initializing RAG components" string is dropped in favour
     of per-step descriptions.
  1. Vault and codebase phases are driven by the reporter via the
     indexers themselves; the CLI only calls the indexer entry points
     with the constructed reporter. Final summary table remains printed
     after the Progress context closes.
  1. Dry-run and MCP-delegation branches are updated only as needed to
     take the new required argument plumbing — dry-run can pass a
     `NullProgressReporter`; MCP delegation already returns before any
     in-process indexing and remains unchanged.

- `Phase 5 — call-site lockstep update`

  1. `src/vaultspec_rag/api.py` — public facade entry points that invoke
     the indexers. Update to accept an optional `reporter` parameter and
     forward it; construct a `NullProgressReporter` internally when the
     caller supplies none, so the facade stays ergonomic for library
     consumers.
  1. `src/vaultspec_rag/mcp_server.py` — MCP tool handlers that call
     `full_index` / `incremental_index`. MCP has no terminal; pass a
     `NullProgressReporter`. Phase events are not yet wired to MCP
     streaming in this phase (out of scope — the ADR keeps it as a
     future consideration).
  1. `src/vaultspec_rag/watcher.py` — the watcher calls
     `incremental_index` on debounce. Pass a `NullProgressReporter`.
  1. `src/vaultspec_rag/service.py` — HTTP service entry points that
     reach the indexers. Pass `NullProgressReporter` unless the service
     already has a compatible progress surface (verify; do not invent
     new surfaces here).
  1. Test call sites — update every fixture and test that constructs a
     `VaultIndexer` or `CodebaseIndexer` and calls `full_index` or
     `incremental_index`: `tests/test_indexer_unit.py`,
     `tests/integration/test_indexer_integration.py`,
     `tests/integration/test_codebase_integration.py`,
     `tests/integration/test_performance.py`,
     `tests/integration/test_api_integration.py`,
     `tests/integration/conftest.py`, `tests/conftest.py`,
     `tests/test_service_registry.py`, and
     `tests/benchmarks/bench_rag.py`. All receive a
     `NullProgressReporter` unless the test is specifically validating
     progress behaviour.

- `Phase 6 — tests for progress behaviour`

  1. Extend `test_progress_unit.py` (from Phase 1) with a
     `CountingProgressReporter` fixture class that records every
     `phase_start`/`advance`/`phase_end` event as a tuple list.
  1. Add `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py`
     — a real-GPU smoke test that runs `VaultIndexer.full_index` and
     `CodebaseIndexer.full_index` against the existing integration
     corpora with a `CountingProgressReporter`. Assertions: every
     expected phase appears exactly once, per-phase `advance` totals
     match the corpus document/chunk counts, and `phase_end` follows
     each `phase_start`. No mocks, no patches, no `pytest.skip` — uses
     the real GPU fixtures already in `integration/conftest.py`.
  1. Ruff and pytest green across the affected modules.

## Parallelization

Phase 1 (the `progress.py` module) is the strict prerequisite for
everything else and must land first. Phases 2 and 3 are independent of
each other and can be executed in parallel once Phase 1 is green —
`VaultIndexer` and `CodebaseIndexer` share no mutable state. Phase 4
(CLI rewrite) depends on Phases 2 and 3 because it exercises the new
indexer signatures end-to-end. Phase 5 (call-site updates) can run in
parallel with Phase 4, but the full test suite cannot go green until
both Phase 4 and Phase 5 have landed together — partial updates will
break the required-kwarg contract. Phase 6 (progress-specific tests)
comes last because it depends on the final indexer surface.

Recommended execution order: Phase 1 → (Phases 2 + 3 in parallel) →
(Phases 4 + 5 in parallel) → Phase 6.

## Verification

Mission success criteria, mapped to the ADR:

- A user running `vaultspec-rag index` against a non-trivial corpus sees
  continuous visible feedback from invocation to completion: init
  sub-steps, vault discovery count, a per-document bar ticking through
  the embed phase, a codebase chunk bar, and final summary. No silent
  windows longer than the cost of a single disk scan.
- `src/vaultspec_rag/indexer.py` and `src/vaultspec_rag/embeddings.py`
  contain zero references to `rich` (verified via grep).
- Every call site of `full_index` / `incremental_index` compiles and
  runs with the required `reporter` kwarg; `ruff check` and
  `pytest src/vaultspec_rag/tests/` pass on the full suite.
- The integration progress test asserts the counting reporter observed
  the right totals on real corpora — not a tautology, not a mock.
- Non-TTY behaviour verified manually by piping `vaultspec-rag index`
  to a file and confirming the output is one clean line per phase with
  no ANSI escapes and no live-frame spam. The ADR commits to this as a
  first-class requirement, and it cannot be confirmed by the test
  suite alone — a manual pipe test is part of sign-off.

Verification commands:

- `uv run ruff check src/vaultspec_rag/`
- `uv run ruff format --check src/vaultspec_rag/`
- `uv run vaultspec-rag test src/vaultspec_rag/tests/test_progress_unit.py -q`
- `uv run vaultspec-rag test src/vaultspec_rag/tests/ -q` (full suite)
- `uv run vaultspec-rag index` against the worktree itself, piped
  through `tee /tmp/index.log`, for the manual non-TTY confirmation.

Honest caveat: the test suite can verify that the reporter is *called*
with the right totals, but it cannot verify that the Rich frames
*look* right to a human. The manual run against the live terminal is
load-bearing for UX validation and must be performed before merge.
