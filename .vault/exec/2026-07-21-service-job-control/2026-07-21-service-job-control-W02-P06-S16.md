---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S16'
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
     The S16 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Implement manager-owned dispatch, token propagation, reconciliation attempts, truthful acknowledgement, completion callbacks, and bounded joins using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/job_manager.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement manager-owned dispatch, token propagation, reconciliation attempts, truthful acknowledgement, completion callbacks, and bounded joins using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/job_manager.py`

## Description

- Route compatibility reindex submission through canonical manager admission,
  exact-ID legacy projection, durable start, and manager-owned dispatch.
- Own each attempt's asynchronous task, worker thread, run-control token, index
  capacity, project lease, writer span, and code pipeline state in one manager.
- Propagate the exact token through real vault and code indexing and reconcile a
  resumed rebuild non-destructively under the same logical job ID.
- Commit control intent before signalling workers, serialize completion against
  concurrent desired-state changes, and preserve application failures over control.
- Clear physical execution ownership after the worker and limiter return, retry
  dirty completion generations, and withhold callbacks until completion is durable.
- Shield bounded joins from cancellation and hand cross-thread resumes back to the
  attempt's owning event loop.

## Outcome

Vault and code compatibility starts now create one canonical job, bind their
production runner, and dispatch through `JobManager`. Pause and cancellation
acknowledge only after the attempt task, worker, capacity, lease, writer, and
pipeline ownership have cleared. Resume either safely withdraws an undelivered
pause after the running transition is durable or queues attempt reconciliation
under the same ID when delivery already won.

Real direct probes covered same-ID pause/resume, forty cross-thread
completion/resume races, application-error precedence, non-cancelling timeout
joins, foreign-loop handoff, and actual filesystem persistence failures. A
recovered dirty `resume_requeued` generation dispatched attempt 2 and emitted
callbacks only after durability. The focused existing suite passed 84 cases
with 2 GPU cases deselected; the GPU/import/static boundary set passed 8 cases.
Ruff, ty, BasedPyright, and `git diff --check` passed. Independent re-review
finished approved at Critical 0, High 0, Medium 1, Low 0.

## Notes

The two live GPU facade regressions could not reach application assertions. The
first invocation inherited the editable main-worktree service and failed the
managed-singleton containment guard; the corrected isolated-branch invocation
then stopped because the required pinned Qdrant server binary is not installed.
Neither failure reached indexing code, and no further retry was made.

The audit retains one Medium follow-up: `jobs.py` is still an 859-line legacy
registry plus compatibility projection and duplicated source-specific runners.
Lifecycle authority is manager-owned and imports remain acyclic, but the facade
should be decomposed before additional orchestration policy accumulates there.
Semantic RAG refresh was not retried because this execution context already
records a CUDA out-of-memory result for that path. No temporary probe remains.
