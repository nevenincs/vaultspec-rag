---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `service-job-control` `W02.P05` summary

Code indexing now carries cooperative control through CPU preparation, the
bounded process-pool pipeline, the sole embedding consumer, storage mutation,
and metadata publication while preserving valid destructive publication spans.

- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

Full, incremental, and scoped code indexing propagate a backward-compatible
run-control token through scanning, hashing, chunking, process-future waits,
bounded queue operations, embedding slices, storage writes, and shutdown.
Controlled unwind cancels queued work, joins owned CPU workers, terminates the
sole consumer, and preserves application and pool failures over control signals.

Clean rebuilds reject requests already pending before collection destruction.
Requests arriving after destruction remain pending through recreation,
replacement, stale cleanup, and atomic metadata publication. Incremental
replacement applies the same protection from old-chunk deletion through current
chunks and metadata, while new-only publication remains interruptible.

Real-behavior tests use production indexers, a real CPU-backed
SentenceTransformer, local Qdrant, real files, threads, processes, locks, and
tokens. They prove pause and cancellation resource unwind, post-control write
cessation, fresh-attempt convergence, and valid clean and scoped publication.
The final S15 module passed 7 cases; its adjacent code, GPU, progress,
worker-parity, job-control, and centralized-Torch set passed 51 cases. Phase
verification also passed Ruff, Ruff formatting, ty, BasedPyright, and
`git diff --check`. Independent S13 through S15 reviews ended at Critical 0 and
High 0 after all findings were remediated.
