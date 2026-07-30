---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
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

# `service-quiesce` audit: `w02 resume recovery`

## Scope

Read-only review of the W02 resume-recovery changes in `service.py`,
`service_quiesce.py`, and the job-manager control and result model against the
accepted service-quiesce ADR and W02 plan. The review also examined the focused
CPU-only controller, registry-transition, and managed-job tests for durable
ordering, retry convergence, ownership, and dispatch races. No service process,
GPU allocation, or external network operation was used.

## Findings

### resume-persistence-publication | high | Registry drops whether a failed recovery write was published

`JobManagerControl.prepare_quiesced_resume` correctly returns
`QuiescedResumeResult.persistence_published` and retains a published queued
generation while rolling back an unpublished one. `ServiceRegistry._resume_resources_once`
then checks only `status` and converts both cases to the identical
`resume_recovery_failed` transition with the fixed
`job_resume_persistence_failed` reason. The returned controller snapshot and
transition therefore discard the observable difference between a generation
that may already be visible after replacement and one that was restored in
memory. That loses the ADR-required persistence outcome truth before W03 can
render the lifecycle envelope or an operator can determine which retry state
was retained.

### recovery-dispatch-coalescing | medium | Concurrent recovery scans can enqueue duplicate dispatch callbacks

`JobManagerControl._schedule_recoverable_quiesced_jobs` selects recoverable
queued IDs under the manager lock but releases that lock before calling
`_schedule_dispatch`. Two already-running resume scans can both select the
same runtime-free queued ID and, when its owner loop is different, enqueue two
`call_soon_threadsafe` callbacks before either callback claims runtime
ownership. `dispatch` prevents a second attempt when the callbacks execute,
but the controller contract and W02 proof requirement also prohibit duplicate
dispatch. The method reports the ID to both callers even though only one
callback can actually own the attempt.

### registry-recovery-proof | medium | CPU tests do not exercise the registry's durable recovery boundary

The new manager tests exercise an unpublished real filesystem failure and a
manually completed controller restart path, while the existing
`test_service_registry_quiesce_transitions.py` tests only empty-manager GPU
transition single flight. No test drives `ServiceRegistry.resume_resources`
with a paused or queued desired-running job, proves that its persistence
finishes before `complete_warming`, or uses concurrent registry resume callers
through a recovery failure and repaired retry. There is also no test for the
published-but-not-durable persistence outcome. Consequently the focused suite
passing does not prove W02.P04.S12's registry-owned ordering, coalesced retry,
and fail-closed recovery acceptance criteria.

## Recommendations

- For `resume-persistence-publication`, preserve the typed persistence result
  through the registry transition so the failure code or structured recovery
  evidence distinguishes published uncertainty from an unpublished rollback.

- For `recovery-dispatch-coalescing`, add an atomic pending-dispatch claim under
  the manager lock, clear it on every dispatch outcome, and make each recovery
  caller report only the ID whose callback it claimed.

- For `registry-recovery-proof`, add CPU-only real-thread registry tests with a
  real manager and filesystem writer for persistence-before-admission, both
  persistence publication outcomes, repaired retry, already-running scan, and
  one recovery dispatch per logical job.

## Reconciliation

Current source resolves `resume-persistence-publication`: the manager exposes exhaustive typed status and persistence enums, and the registry preserves unpublished rollback versus published-but-not-durable retention as distinct fail-closed reasons while remaining in `warming`. S11 and S14 are satisfied at this boundary. W03 still owns the public lifecycle envelope.

Current source also resolves `recovery-dispatch-coalescing`: an exact-attempt token is claimed under the manager lock, binds dispatcher and generation nonces, and is consumed through canonical dispatch. Checked-in CPU tests cover concurrent and loopless claims, cancellation and shutdown before a blocked callback, and recovery after missing or stopped loop ownership. S17 is satisfied at the manager boundary.

`registry-recovery-proof` remains open. A partial real registry test now covers an unpublished filesystem failure, a durable queued generation, and concurrent successful transition coalescing, so the original statement that only empty-manager registry tests exist is historical rather than current. The test still reads persistence only after `resume_resources` returns, binds no runner, exercises no registry-owned dispatch, and does not drive an unpublished failure followed by concurrent repaired retry. It therefore does not prove persistence-before-admission-and-execution or one registry dispatch claim reaching one attempt. S12 and W02 remain incomplete.

No deterministic real post-replace directory-sync failure is portable on Windows. The release gate requires real unpublished failure and durable queued restart evidence plus exhaustive typed published-not-durable propagation; it must not introduce a fake, patch, monkeypatch, skip, or xfail to manufacture that operating-system outcome. No service process, RAG endpoint, CUDA allocation, GPU test, or CPU test was run during this reconciliation.

### S12 focused follow-up

Commit `bbf02d53` resolves the remaining `registry-recovery-proof` finding. The focused evidence now uses the real registry, manager persistence writer, filesystem, service-loop thread, bound runner, and concurrent resume threads. With the loop callback blocked, it observes the durable queued desired-running attempt 2 and reopened epoch before runner execution. After a real unpublished failure and directory repair, two resume callers share one transition object, one epoch increment, one dispatch-claim generation, and one same-ID attempt, with no pending claim left behind.

S11 and S14 continue to own the exhaustive typed persistence truth, S17 continues to own manager-level token and loop races, and S12 now proves their registry composition. This closes the three findings in this audit. It does not complete W02: S16 still owns the canonical retryable HTTP 503 mapping for closed search admission, and S18 still owns CPU proof that the refusal retains no project, model, reranker, or CUDA state. No service process, RAG endpoint, CUDA allocation, GPU test, or CPU test was run during this acceptance reconciliation.

### Final W02 acceptance reconciliation

The independent loopless-callback finding is rejected. The real trace does not reproduce its premise: `_dispatch_admission_locked` clears every refusal before claim consumption and atomically consumes the exact claim before `_dispatch_on` calls the loop's task factory. A real task-factory failure therefore occurs after the pending claim has already been removed; it cannot strand the alleged pending callback claim. Missing, closed, stopped, rejected, timed-out, stale, cancelled, and shutdown paths either clear, consume, or supersede the exact claim. No source change was justified by that finding, and no unproven repair was committed.

S16 and S18 are also satisfied. The landed service route maps the typed closed-admission exception to the canonical retryable HTTP 503 envelope for every public source, and the checked-in production-route proof demonstrates that the same real registry retains no project, model, reranker, CUDA state, or compute ticket. Commit `18977d3c` strengthens the proof with the complete health and unchanged quiesce snapshot, including released VRAM and acknowledged GPU safety. The guard record states the exact mutation that makes the named 503 assertion fail.

The final committed W02 evidence is `b0d28a30` for canonical manager recovery dispatch and lifecycle-owned manager lookup, `cf9a0b1e` for serialized capped project admission, `85fa25f2` for registry-owned exclusive cleanup, `bbf02d53` for durable registry recovery ordering and repaired concurrent retry, and `18977d3c` for the closed-search ownership boundary. Together with the retained Sol contracts and the earlier landed typed route and recovery implementation, S11 through S18 are satisfied and W02 is complete. W03 and W04 remain separate open waves; W02 completion does not claim their public lifecycle or borrower-orchestration work.

This was a static acceptance reconciliation of current source, committed diffs, and checked-in proof. No service process, RAG endpoint, CUDA allocation, GPU test, CPU test, lint, type-check, or other runtime gate was run.
