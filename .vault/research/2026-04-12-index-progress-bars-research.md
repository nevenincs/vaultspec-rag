---
tags:
  - '#research'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-reference]]'
  - '[[2026-04-12-index-progress-bars-adr]]'
---

# index-progress-bars research

## Scope

Issue #62 asks for visible, granular progress feedback across the whole
`vaultspec-rag index` pipeline. This note records the investigation that
fed the ADR. Because the problem is concrete and localised to a small
set of existing modules, a full open-ended research phase was unnecessary;
the investigation took the form of a code reference audit
(see `[[2026-04-12-index-progress-bars-reference]]`), supplemented by the
targeted question list below.

## Current State

- `cli.py` is the only Rich-aware surface. It already imports `Console`,
  `Progress`, `SpinnerColumn`, `BarColumn`, and `TextColumn`, and drives a
  single `Progress` context with three coarse tasks: init, vault, code.
  Each coarse task advances exactly once when its phase finishes.
- `VaultIndexer.full_index` / `incremental_index` and the `CodebaseIndexer`
  counterparts parse documents in a `ThreadPoolExecutor` and embed with
  one or two batched `SentenceTransformer.encode()` calls. Neither indexer
  has any callback, observer, or progress hook.
- `embeddings.encode_documents` / `encode_documents_sparse` forward the
  full list into `SentenceTransformer.encode(list, batch_size=...)`. The
  library exposes an internal `show_progress_bar` flag, but it is
  dense-only, unstyled, and cannot be composed with a Rich `Progress`.
- The CLI drives vault and codebase indexing sequentially inside one
  `with progress:` block; two stacked task rows is the natural UX and
  needs no concurrency primitives at the CLI layer.
- The project forbids mocks, stubs, and skips in tests. Any progress hook
  must be exercisable against real corpora on the real GPU.

## Gaps Identified

- No signal at all during the long embed phase — users cannot tell a
  wedged process from one making progress.
- The init phase (workspace resolve, config, dense model, sparse model,
  reranker, store open) is silent despite containing several multi-second
  sub-steps.
- Discovery, hashing, parsing, chunking, upsert, and metadata-write phases
  are all reported only post-hoc.
- Non-TTY runs (CI logs, piped output) currently emit the Rich live-frame
  regardless, which spams logs.

## Options Considered for the Reporter Contract

- **Plain callable** `Callable[[str, int, int], None]`. Rejected: the CLI
  needs distinct signals for *total-known*, *advance*, *phase-start*, and
  *phase-end*; collapsing them into one callable either bloats the
  signature or demands sentinel values.
- **Inject `rich.Progress` directly into the indexer.** Rejected: leaks
  Rich into `indexer.py` and `embeddings.py`, violating separation of
  concerns.
- **Lightweight `ProgressReporter` Protocol** with `phase_start`,
  `advance`, `phase_end`, `log`. Chosen. The indexer depends only on a
  `typing.Protocol`; the CLI supplies a `RichProgressReporter` adapter.
  A `NullProgressReporter` no-ops when no reporter is supplied.

## Embed-Phase Granularity: Slice vs Callback

Two ways to surface per-document advance during embedding were weighed:

- **Slice at the indexer layer** — call `encode_documents` repeatedly on
  sub-batches of size `progress_batch_size` and advance between slices.
  Keeps `embeddings.py` untouched; granularity is tunable from the
  indexer; the only cost is a handful of additional Python-level
  `.encode()` calls per run (negligible next to GPU time).
- **Pass a `callback` kwarg into `encode_documents`.** Leaks progress
  semantics into the embeddings module, and `sentence-transformers`
  exposes no public per-batch hook that can be cleanly wrapped — we'd
  be re-implementing the slicing anyway.

Slicing at the indexer layer was selected. It keeps `embeddings.py` a
pure GPU-facing surface and localises the progress concern to the one
module that also owns document discovery.

## Multi-Corpus UX Decision

`handle_index` runs vault and codebase sequentially. A single
`rich.Progress` with two or three stacked task rows matches the existing
orchestration and needs no concurrency design. The init task stays and is
expanded into explicit `phase_start` calls around its real sub-steps;
vault and codebase tasks become per-document/per-chunk bars with totals
set once discovery completes.

## Non-TTY Handling

Rich's `Console` already auto-detects non-TTY stdout and honours
`NO_COLOR`. The remaining gap is that a non-TTY run still emits the full
live-updating frame. The `RichProgressReporter` checks
`console.is_terminal`; when `False`, it downgrades to line-based output
(`phase_start` / `phase_end` print one line each; `advance` is a no-op).
This is a pure adapter-level switch — no new dependencies, no new env
vars beyond what Rich already reads.

## Thread Safety

Rich's `Progress.update()` is documented as thread-safe, so the threaded
parse phase can call `reporter.advance()` from worker threads without
extra coordination. The line-based fallback guards its counter with a
`threading.Lock`.

## Outcome

The findings above informed the ADR's choice of a Protocol-based reporter
with an indexer-side slicing strategy and a TTY-aware adapter. No further
open questions blocked the ADR.
