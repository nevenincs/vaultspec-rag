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
