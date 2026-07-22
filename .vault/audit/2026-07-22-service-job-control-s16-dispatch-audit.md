---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-research]]"
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

# `service-job-control` audit: `Manager-owned dispatch`

## Scope

Reviewed the S16 changes in `src/vaultspec_rag/job_manager.py` and
`src/vaultspec_rag/jobs.py` against the accepted desired-state architecture, the S16
plan contract, the repository's service-domain and resource-ownership rules, and the
explicit requirement that `jobs.py` remain a small compatibility/dispatch facade. The
review traced dispatch durability, exact task and token ownership, pause/resume/cancel
races, application-result precedence, reconciliation attempts, physical-resource
release, callback ordering, bounded shielded joins, strong task references, clean-resume
convergence, public re-export identity, and import direction. Focused verification ran
`uv run pytest src/vaultspec_rag/tests/test_jobs_unit.py -q` (47 passed); those existing
tests do not execute the new `bind_dispatch`, `dispatch`, worker teardown, callback, or
bounded-join paths.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### Manager-owned dispatch | {level} | {summary}

     followed by a paragraph carrying the detail. Manager-owned dispatch is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### Manager-owned dispatch | high | Resume withdraws live pause before the running transition is durable

`_request_resume_locked` calls `RunControlToken.request_resume()` while
`set_desired_state` has not yet called `_persist_locked`. When the pause has not been
delivered, the token is therefore cleared before the new `running` intent/state is
durable. The worker can cross checkpoints and continue during the persistence write; if
that write fails, rollback re-arms pause only after this window. This reverses the
required durable-transition-before-signal ordering and permits work to proceed under the
old durable pause intent.

### Manager-owned dispatch | high | Completion branches on a stale control snapshot and can strand a finished attempt

`_complete_attempt` reads the job with `get()`, releases the manager lock, and later
chooses `acknowledge_control` or `finish_attempt` from that snapshot. If a worker returns
success while the job is `pausing`, the callback can observe control pending; a concurrent
resume can then withdraw the undelivered pause and restore `running` before
`acknowledge_control` acquires the lock. The acknowledgement is ignored because the job
is now `running`, but the success result is never committed and the completed task remains
the runtime owner. The logical job is permanently reported as running with no live worker.

### Manager-owned dispatch | high | Teardown persistence failures are ignored and leave control acknowledgements wedged

`_run_worker_attempt` ignores the boolean result of `release_execution_resources`.
When its atomic persistence write fails before publication, the method restores the prior
`worker_active` and held-resource snapshot even though the physical thread, limiter,
lease, writer, and pipeline have unwound. `_complete_attempt` then receives
`resources_still_owned` from `acknowledge_control`, invokes the completion callback anyway,
retires its strong task reference, and provides no path to replay the release transition.
The job remains indefinitely `pausing` or `cancelling` with a completed task attached;
`flush_persistence` can only durably preserve that stale ownership.

### Manager-owned dispatch | medium | The compatibility facade was expanded instead of decomposed

`jobs.py` is now 859 lines and the S16 patch adds both duplicated vault/code execution
runners and manager-to-legacy synchronization beside the full legacy registry. The
canonical model and manager identities are re-exported correctly and import direction is
acyclic, but the explicit decomposition goal is not met: execution policy, resource
instrumentation, admission, legacy projection, callbacks, and public compatibility remain
coupled in one module. This makes the facade the next lifecycle implementation surface
rather than a thin adapter.

## Recommendations

Make resume a two-phase, race-safe manager operation in which durable intent is committed
before the token can permit more work, with deterministic reconciliation if delivery wins
the race. Replace `_complete_attempt`'s unlocked read/branch sequence with one atomic
manager transition that consumes the exact attempt exit and current desired state under
the manager lock. Treat resource-release persistence as a required completion step: retain
the task and retry or durably reconcile bookkeeping before acknowledging control or
calling completion callbacks. Add real-behavior dispatch tests for all three races,
including an actual filesystem persistence failure and assertions that no task, worker,
limiter, lease, writer, or pipeline ownership survives acknowledgement.

Extract the vault/code attempt runners and legacy projection callbacks into focused
modules, leaving `jobs.py` with stable re-exports and small compatibility entry points.
Preserve the verified identity re-exports, one-way import graph, non-destructive resumed
clean behavior, application-failure precedence, strong live-task ownership, and shielded
bounded join design.

Review verdict: changes requested. Severity counts: Critical 0, High 3, Medium 1, Low 0.

## Remediation verification

Re-review verified that all three High findings are closed.

- Resume now first persists the `running` state and desired state, then attempts token
  withdrawal while holding the manager lock. If checkpoint delivery wins, the manager
  restores and persists observed `pausing` with desired `running`, allowing cleanup to
  queue the same-ID reconciliation attempt without a false running acknowledgement.
- `_complete_attempt` now reads current control state and invokes finish or acknowledgement
  inside one `RLock` scope, so a concurrent desired-state mutation cannot invalidate the
  branch. Resumed dispatch compares the caller's loop with the binding's stored owner and
  uses thread-safe handoff for foreign-loop and no-loop callers.
- Resource ownership is cleared only after AnyIO returns from the synchronous worker and
  releases its limiter. That irreversible cleared state remains truthful in memory when
  persistence fails; completion retries the full generation, suppresses callbacks while
  nondurable, and preserves `resume_requeued` after successful retry so convergence is
  dispatched rather than stranded.

Application exceptions still take precedence over cooperative control, exact attempt/task
checks prevent stale completion, terminal archival releases runtime and dispatch bindings,
live tasks retain strong references until completion handling finishes, and bounded joins
continue to shield rather than cancel worker-backed tasks. Resumed clean jobs still execute
non-destructive reconciliation. Public identities remain direct re-exports and the import
graph remains one-way.

Reviewer verification completed with `git diff --check`, Ruff over both changed modules,
and the focused job/control unit suites (64 passed). The executor additionally reported its
84-pass gate and real direct probes for filesystem persistence failure and flush recovery,
callback suppression, forty cross-thread completion races, cancel/error precedence, and a
bounded non-cancelling join.

The Medium facade finding remains open: `jobs.py` still combines legacy registry,
compatibility projection, admission, callbacks, and duplicated source-specific runners.
It does not invalidate the corrected S16 lifecycle behavior, but should be resolved by the
planned module-boundary follow-up before more orchestration policy accumulates there.

Re-review verdict: APPROVED with Medium follow-up. Current severity counts: Critical 0,
High 0, Medium 1, Low 0.
