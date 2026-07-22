---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
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
     The S21 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Verify real watcher pause coalescing, cancellation dirtiness, replacement expectations, explicit watcher stop, and cleanup joining using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify real watcher pause coalescing, cancellation dirtiness, replacement expectations, explicit watcher stop, and cleanup joining using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Migrate watcher integration coverage from standalone stores to the canonical
  production registry, manager, and server watcher owner.
- Isolate managed status, local Qdrant storage, limiter state, watcher drains,
  project slots, and manager state for every watcher test.
- Verify paused watcher work releases its task, worker, capacity, lease, writer,
  and pipeline ownership while retaining one convergence job.
- Add later filesystem dirtiness while paused and prove resume uses the same job
  ID, creates a reconcile attempt, and indexes both generations.
- Stop watcher intake while the resumed attempt is blocked on the real writer
  lock and prove cleanup remains pending until the attempt naturally releases.
- Cancel a live watcher attempt, prove watcher intake stays enabled, and verify a
  delayed distinct-ID replacement converges retained and later dirtiness.
- Preserve and re-run the existing watcher detection and cooldown regression
  coverage through the manager-owned runtime.

## Outcome

The target integration file now exercises one production ownership path from
filesystem intake through `JobManager`, the registry lease, real indexers, local
Qdrant storage, and bounded watcher cleanup. The obsolete double-store topology
that failed after watcher execution moved into the manager was removed.

The two new lifecycle cases passed together, and the full target file passed all
seven tests. Ruff lint and formatting passed, BasedPyright reported zero errors
and warnings, scoped Xenon and cognitive-complexity gates passed, the
prohibited-test-double scan found no matches, and `git diff --check` passed.
Independent review approved the step with zero critical, high, medium, or low
findings.

## Notes

The initial five-test baseline produced three passes and two failures because
the old tests held a standalone local store while manager-owned watcher work
opened the canonical registry store for the same root. The corrected topology
uses one real registry slot and resolves that storage-lock conflict without
weakening any assertion.

The isolated worktree had no semantic code or vault index, so grounding used the
documented full-source and exact-symbol fallback. No production files changed,
no test was skipped or marked as an expected failure, and no data was lost.

`W03.P11` remains open because `S22` is not complete, so no Phase Summary is
created by this step.
