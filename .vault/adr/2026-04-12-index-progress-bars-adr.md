---
tags:
  - '#adr'
  - '#index-progress-bars'
date: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-reference]]'
  - '[[2026-04-12-index-progress-bars-research]]'
---

# `index-progress-bars` adr: granular per-document progress reporting | (**status:** `accepted`)

## Problem Statement

The `vaultspec-rag index` command runs in near-silence between invocation and
completion. The current CLI uses a single Rich `Progress` instance with three
coarse tasks (init, vault, code) that advance exactly once when each phase
finishes, offering no feedback during the long embedding phase. Users indexing
a non-trivial vault or codebase cannot distinguish a stuck process from one
making progress. Every significant pipeline phase — workspace resolution, model
load, discovery, hashing, parsing, chunking, embedding, upsert, metadata write
— is silent until after it completes.

Issue #62 requires visible, granular feedback across the whole pipeline, with
a per-document progress bar driving the long embedding phase, without coupling
the indexer to Rich and without changing indexing semantics or performance.

## Considerations

The ground truth for current state is captured in the reference audit
(see `related`). Key facts drawn from it:

- `cli.py` already imports Rich (`Console`, `Progress`, `SpinnerColumn`,
  `BarColumn`, `TextColumn`) and owns the only Rich-aware surface.
- `VaultIndexer.full_index` / `incremental_index` and the corresponding
  `CodebaseIndexer` entry points parse documents in a `ThreadPoolExecutor`
  and embed in one or two batch `.encode()` calls. No callback or observer
  pattern exists in either indexer.
- `embeddings.encode_documents` / `encode_documents_sparse` call
  `SentenceTransformer.encode(list, batch_size=…)` once with the full list.
  `sentence-transformers` exposes an internal `show_progress_bar` flag, but
  it is dense-only, unstyled, and cannot be composed with a Rich `Progress`.
- The CLI drives vault and codebase indexing **sequentially** inside one
  `with progress:` context; two stacked task bars in a single `Progress`
  instance is the natural UX and needs no concurrency primitives.
- Rich's `Progress` is documented as thread-safe for `advance()` / `update()`
  calls, which matters because the parse phase is already threaded.
- The project forbids mocks, stubs, and skips in tests; the progress hook
  must be exercisable with real corpora on real GPU.

Shape options considered for the progress contract:

- **Plain callable `Callable[[str, int, int], None]`** — simple, no imports.
  Signature: `(phase, advance, total)`. Rejected as too weak: the CLI needs
  distinct signals for *total-known*, *advance*, *phase-start*, *phase-end*,
  and conflating them into one callable either bloats the signature or
  forces sentinel values.

- **Rich `Progress` injected directly** into the indexer — simplest to wire, but leaks Rich
  into `indexer.py` and `embeddings.py`, violating separation of concerns.
  Rejected.

- **Lightweight `ProgressReporter` Protocol** (chosen). A
  `typing.Protocol` in a new `progress.py` module with four methods:
  `phase_start(name, total)`, `advance(n=1)`, `phase_end()`, and
  `log(message)`. The indexer depends only on the Protocol; the CLI
  supplies a `RichProgressReporter` adapter that drives a `rich.Progress`
  instance. A `NullProgressReporter` no-ops when no reporter is supplied,
  preserving the current public API of `VaultIndexer`/`CodebaseIndexer`.

Per-document boundaries in the embed phase:

- `SentenceTransformer.encode()` takes the full list at once and internally
  chunks into `batch_size`. Two options to surface per-document advance:

  1. **Slice at the indexer layer**: the indexer calls `encode_documents`
     repeatedly on chunks of size `progress_batch_size` (default 32) and
     calls `reporter.advance(len(chunk))` between slices. Pros: no change
     to `embeddings.py` public API, progress granularity tunable from the
     indexer, thread-safety stays at the Rich layer. Cons: marginally
     more Python-level overhead per batch (negligible next to GPU time).

  1. **Pass a `callback` kwarg into `encode_documents`**: adds an optional
     `on_batch_complete` callable parameter to `embeddings.py`. Pros: keeps
     the embedding call single. Cons: leaks progress semantics into the
     embeddings module, and `sentence-transformers` has no public hook we
     can cleanly wrap — we'd be re-implementing the slicing anyway.

  **Chosen: option 1.** Slice at the indexer, keep `embeddings.py` untouched.

Multi-corpus UX:

- One `rich.Progress` instance, two or three stacked task rows. The init
  task stays (model load has sub-steps: workspace, config, dense model,
  sparse model, reranker, store open). Vault and codebase tasks become
  *per-document* bars with `total=len(docs)` once discovery completes. The
  reporter's `phase_start` swaps the active task and resets its total.

Non-TTY / `NO_COLOR`:

- Rich's `Console` already auto-detects non-TTY stdout and strips ANSI; it
  also honours `NO_COLOR` via env var per the Rich docs. The only gap is
  that a non-TTY run still emits the full live-updating progress frame,
  which spams logs. The `RichProgressReporter` will check
  `console.is_terminal`; when `False`, it downgrades to line-based output
  (`phase_start` and `phase_end` print one line each, `advance` is a no-op).
  This is a pure adapter-level switch — no new dependencies, no env var
  parsing beyond what Rich already handles.

Thread safety:

- `RichProgressReporter.advance()` delegates to `rich.Progress.update()`,
  which is thread-safe. The fallback line-based reporter guards its counter
  with a `threading.Lock`. The indexer's `ThreadPoolExecutor` parse phase
  can therefore call `reporter.advance()` from worker threads without extra
  coordination.

## Constraints

- No new dependencies. Rich is already in the dep tree.
- `indexer.py` and `embeddings.py` must not import `rich`.
- `VaultIndexer.full_index`, `VaultIndexer.incremental_index`, and the
  `CodebaseIndexer` counterparts are re-implemented to take `reporter`
  as a **required** positional/keyword argument. No backwards-compatible
  defaults, no shims, no deprecation path — every call site is updated
  in the same change. This is a straight re-implementation.
- No change to indexing algorithm, batch sizes, chunking, or wall-clock
  performance beyond the unavoidable cost of slicing the embed call into
  sub-batches (a handful of extra Python-level `.encode()` calls per run;
  negligible next to GPU compute).
- Test mandate: the progress smoke test must drive real corpora through
  the real indexer on real GPU. No mocks, no patches, no stubs.
- Scope is strictly progress reporting. No UI polish beyond what's needed
  to make progress visible. No new CLI flags unless required to toggle the
  non-TTY fallback for testing (and even then, prefer env-based detection).

## Implementation

High-level shape (details defer to the plan document):

- New module `src/vaultspec_rag/progress.py` defining:

  - `ProgressReporter` (`typing.Protocol`) with
    `phase_start(name: str, total: int | None)`,
    `advance(n: int = 1)`, `phase_end()`, `log(message: str)`.
  - `NullProgressReporter` — no-op implementation. Used only in tests
    and internal callers that genuinely want silence; never a default.
  - `RichProgressReporter` — adapter holding a `rich.Progress` instance
    plus the current task id; TTY-aware with a line-based fallback branch.

- `indexer.py`:

  - `VaultIndexer.full_index` and `incremental_index` take
    `reporter: ProgressReporter` as a required keyword argument. All
    existing call sites (CLI, MCP server, watcher, API facade, tests)
    are updated in lockstep.
  - Calls: `phase_start("scan", …)` around discovery;
    `phase_start("hash", total=len(docs))` with `advance(1)` inside the
    hash loop; `phase_start("parse", total=len(docs))` with `advance(1)`
    inside the `ThreadPoolExecutor.as_completed` consumer;
    `phase_start("embed", total=len(docs))` wrapping a sub-batched
    `encode_documents` loop that calls `advance(len(slice))` after each
    slice; `phase_start("upsert", total=1)` + `advance(1)` around the
    store write; `phase_start("write-meta", total=1)` + `advance(1)`
    around metadata persistence.
  - `CodebaseIndexer` receives the same treatment, keyed on chunk counts
    where the unit of work is a chunk rather than a document (the UX
    label will say "chunks" for codebase, "documents" for vault).

- `cli.py`:

  - `handle_index` constructs a single `RichProgressReporter` wrapping a
    `rich.Progress` with `SpinnerColumn`, `TextColumn(description)`,
    `BarColumn`, `MofNCompleteColumn`, `TimeElapsedColumn`.
  - The existing "init" task is expanded into explicit `phase_start`
    calls surrounding workspace resolve, config load, dense model load,
    sparse model load, reranker load, and store open.
  - Vault and codebase phases are driven via the reporter rather than the
    current coarse single-advance tasks.
  - When `console.is_terminal` is `False`, the reporter routes to the
    line-based fallback and the `rich.Progress` is never started.

- `embeddings.py`: **untouched**. All slicing lives in the indexer.

- Tests:

  - `test_progress_reporter_unit.py`: exercises `NullProgressReporter` and
    the line-based branch of `RichProgressReporter` against a captured
    stream, asserting counter arithmetic and thread-safety under a
    `ThreadPoolExecutor` hammering `advance()`.
  - Extend `test_indexer_integration.py` (or add
    `test_indexer_progress_integration.py`) with a real-corpus smoke test
    that passes a counting `ProgressReporter` implementation and asserts
    the observed totals match the corpus sizes across each phase. Uses
    the existing integration fixtures on the real GPU.

- Nothing in the public CLI surface changes beyond the richer output.
  No new flags, no new env vars, no new commands.

## Rationale

The `ProgressReporter` Protocol is the minimal shape that keeps Rich out of
the indexing modules while giving the CLI enough signal to drive a stacked
Rich `Progress` with accurate totals. It is smaller than a full observer
pattern, and because it is a `Protocol` rather than an ABC, callers never
need to subclass — the default `NullProgressReporter` keeps the existing
call sites working with zero changes.

Slicing the embed call at the indexer layer is strictly better than leaking
progress semantics into `embeddings.py`. The sub-batch loop is a few lines
of straightforward Python and preserves the embeddings module as a pure
GPU-facing surface.

Choosing one `rich.Progress` with stacked task rows matches the existing
sequential orchestration in `handle_index`; there is no concurrency to
design around, and two stacked rows is the idiom Rich is designed for.

The TTY-aware line-based fallback is the minimum safe thing for non-TTY
runs (CI logs, piped output, dumb terminals). Rich already handles colour
stripping, so the fallback only has to solve the live-frame problem.

## Consequences

Positive:

- Users get continuous, accurate feedback across every pipeline phase,
  including per-document updates during embedding — the feature #62 asks
  for.
- The indexer gains a clean, testable Protocol-based hook that other
  callers (the MCP service, future HTTP service, future TUI) can reuse
  without re-inventing progress plumbing.
- Non-TTY behaviour becomes deterministic and log-friendly.

Negative / costs:

- The embed phase is split into N sub-batches of `progress_batch_size`
  instead of one. Overhead is a handful of additional `.encode()` calls
  per run — GPU batch-size semantics are preserved because each slice is
  still passed as a list. Performance impact is expected to be
  unmeasurable.
- Two new public surfaces (`ProgressReporter` Protocol and the `reporter`
  keyword argument on indexer entry points) become part of the package
  API and must be maintained.
- Slightly more surface in `cli.py` to wire up phase transitions; the
  current three-task coarse bar is replaced by a longer sequence of
  `phase_start` calls. This is additive, not a redesign.

Future considerations:

- The same `ProgressReporter` Protocol is the natural seam for a future
  MCP `index` tool that streams progress updates over stdio — the adapter
  would serialise `phase_start`/`advance`/`phase_end` events as JSON
  frames instead of driving Rich. This ADR does not commit to that
  extension; it only ensures the contract is shaped so it is possible.
- If the embed phase becomes chunk-parallelised in a later iteration
  (separate ADR), the `threading.Lock`-guarded line reporter and the
  thread-safe Rich adapter both already handle concurrent `advance()`
  calls, so no contract change is needed.
