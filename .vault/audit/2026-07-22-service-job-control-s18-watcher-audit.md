---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `service-job-control` audit: `S18 watcher convergence`

## Scope

<!-- What was audited and why -->

Reviewed the complete S18 change in `src/vaultspec_rag/watcher.py` against the
accepted service-job-control plan, ADR, research, the audit template, and the
applicable service-domain, CPU-worker, GPU-consumer, GPU-lock, backend-aware
storage-lock, bounded-operator-view, and managed-singleton rules. The review traced
the manager, model, and compatibility seams in `src/vaultspec_rag/job_manager.py`,
`src/vaultspec_rag/job_models.py`, and `src/vaultspec_rag/jobs.py`, including same-path
re-dirtiness, pause unwind and same-ID requeue, immediate queued/paused cancellation,
foreign active-job deduplication, callback-versus-poll idempotence, terminal eviction,
legacy projection, registry lease ownership, cooldown/replacement interaction, dispatch
failure fallback, persistence boundaries, and watcher-stop ownership.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### S18 watcher convergence | {level} | {summary}

     followed by a paragraph carrying the detail. S18 watcher convergence is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### S18 watcher convergence | medium | Legacy projection leaves paused watcher work reported as running

`_sync_legacy_snapshot` projects canonical `paused` and `queued` snapshots only by
calling `record_progress`; it does not change the compatibility record's `phase` from
`running`. The current public legacy jobs view therefore counts a safely unwound paused
watcher job as running and, because a `paused` progress step is not classified as
waiting, can later label it stalled. Canonical `JobManager` state, desired state,
resources, persistence, same-ID resume, and cancellation remain correct, so this is not
an S18 execution-safety blocker. It is nevertheless an operator-truth mismatch until
the `W04.P12.S23` canonical route-shaping step replaces or corrects the compatibility projection.

## Recommendations

<!-- Actionable recommendations -->

Project `queued` and `paused` into a truthful non-running compatibility phase, or make
the operator view consume the canonical manager snapshot before paused watcher control
is exposed. Add the assertion to the planned registry-backed watcher lifecycle coverage
so a paused job is neither counted as running nor classified as stalled.

The convergence implementation is otherwise coherent. Immutable attempt batches keep a
path dirtied during a live attempt pending even when it is the same path; paused work
retains the root/source slot; resume captures retained and later dirtiness under the same
job ID; old attempt-generation entries are removed across pause-withdrawal requeue; and
terminal observation clears capture bookkeeping. Exact slot/job matching makes completion
callbacks and idle polling idempotent. Foreign equivalent work holds the slot without
consuming watcher dirtiness, and completion conservatively triggers a later watcher-owned
convergence. Cancellation preserves dirtiness and schedules a new ID after one bounded,
capped exponential backoff. Admission and bind/dispatch failures retain the empty slot and
dirty set, with fallback scheduling only when terminal observation did not already set the
deadline.

The registry-backed runner loads the model before taking a real project lease, runs the
production incremental indexer with the manager token and exact attempt context, and
releases lease/writer/pipeline reporting before manager acknowledgement. The watcher task
does not falsely cancel manager-owned work in its finalizer; explicit stop and cleanup
joining correctly remain assigned to S19. Durable daemon restoration and rebinding remain
assigned to S20/S22.

Verification evidence reviewed: watcher/filter/config checks passed 9/9; managed real
index-control checks passed 11/11; `src/vaultspec_rag/tests/test_jobs_unit.py` passed
47/47; and Ruff, basedpyright, ty, and diff checks were green. Independent review reran
`src/vaultspec_rag/tests/test_watcher_unit.py` with the job unit suite, producing 54/54
passes, and reran `git diff --check` successfully. A bounded public-registry probe observed
a live project lease and writer span, pause only after resource release, same-ID resume
with intervening dirtiness, cancellation of the next job with dirtiness retained, a
0.998-second replacement delay, and successful convergence under a new ID. A separate
real capacity probe filled the 64-job production bound and showed admission failure kept
the slot empty and dirty, scheduled 1.0 second exactly once, did not increment at 0.5
seconds, then advanced to a 2.0-second retry at eligibility.

Three watcher-control cases remain red because an external daemon refused readiness
connections before their assertions; that is not evidence of an S18 source failure. The
standalone local-store/indexer topology in
`src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` is incompatible
with the new canonical public-registry execution path. Deferring that test migration is
acceptable for this individual production step because W03.P11.S21 explicitly owns real
registry-backed watcher lifecycle verification; no production fallback or test double
should be added. S21 must replace the obsolete topology and restore the relevant suite to
green before the phase or Wave is accepted.

Review verdict: APPROVED with Medium follow-up. Severity counts: Critical 0, High 0,
Medium 1, Low 0.
