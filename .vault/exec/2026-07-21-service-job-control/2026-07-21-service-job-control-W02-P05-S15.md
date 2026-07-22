---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S15'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S15 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Verify real code indexing unwinds producer-consumer resources, preserves mutation safety, and converges after resume using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify real code indexing unwinds producer-consumer resources, preserves mutation safety, and converges after resume using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Exercise pause and cancellation through the production code process pool,
  bounded queue, sole embedding consumer, local Qdrant store, and real token.
- Require each controlled attempt to join its consumer thread and all child
  processes before surfacing the exact control signal.
- Hold the production GPU lock to observe clean and scoped replacement inside
  their protected invalid intervals, then verify current payloads and metadata.
- Reconcile partial publication with a fresh token and require complete current
  files, stored content, and metadata without test doubles or mirrored indexing.

## Outcome

Real-behavior coverage now proves that code indexing pause and cancellation
unwind process-pool producers and the sole consumer without later writes. A
fresh attempt reconciles partial publication to complete current data and
metadata. Clean and scoped replacement tests also prove that control stays
pending while publication is invalid and is delivered only after current point
payloads and changed metadata values are durable.

The focused module passed all 7 cases in 16.75 seconds. The adjacent code, GPU,
progress, worker-parity, job-control, and centralized-Torch regressions passed
51 cases. Ruff, Ruff formatting, ty, BasedPyright, and `git diff --check`
passed. Independent review finished at Critical 0 and High 0 after resolving
one High assertion gap around current metadata values.

## Notes

The tests use a real CPU-backed SentenceTransformer only to keep runtime bounded;
all orchestration, chunking, storage, process, thread, lock, and control behavior
comes from production code. Semantic RAG refresh was not retried because this
execution context records a CUDA OOM for that path. No temporary probes or test
scaffolds remain.
