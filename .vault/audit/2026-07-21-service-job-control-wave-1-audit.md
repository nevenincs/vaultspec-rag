---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-adr]]"
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

# `service-job-control` audit: `Wave 1 state authority`

## Scope

Wave 1 commits were reviewed against the accepted service-job-control ADR, research,
execution plan, project safety rules, and focused verification. The audit covers cooperative
control, canonical resources, manager admission and ownership, lifecycle races, persistence,
restart recovery, and the new unit and integration tests.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### Wave 1 state authority | {level} | {summary}

     followed by a paragraph carrying the detail. Wave 1 state authority is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### legacy-authority-split | high | Actual indexing jobs still bypass JobManager

`JobManager` was added alongside, rather than in place of, the legacy `_records` deque and
unkeyed `_background_tasks` set. `record_start`, `record_progress`, `record_finish`,
`snapshot`, `restore_interrupted`, and both `start_reindex_*` functions still read and write
only the legacy registry, and no production caller owns a `JobManager`. Consequently the
exact-ID manager cannot observe or control any real manual or watcher indexing job, while
the legacy bounded deque can still evict active work. This contradicts W01.P02's replacement
and compatibility-seam contract and blocks every later dispatcher, HTTP, and CLI control
step. Route the legacy helpers through one service-owned manager (or replace their callers)
before building adapters.

### pause-withdrawal-race | high | A delivered pause can leave a dead attempt reported running

`_request_resume_locked` samples `control.snapshot().delivered`, changes the job to
`running`, and then `set_desired_state` persists before calling `request_resume()` without
checking its result. The worker may deliver `PauseRequested` during that persistence window;
the subsequent withdrawal clears the token but cannot retract the already-raised signal.
`acknowledge_control` then ignores the unwind because the manager now reports `running`,
leaving a completed attempt represented as live or detached without a valid state
transition. Make pause withdrawal and the manager transition one race-safe protocol: a
failed/too-late withdrawal must retain `pausing` with desired `running` so cleanup requeues
reconciliation.

### acknowledgement-proof | high | Control acknowledgement does not prove resource release

`acknowledge_control` marks a job `paused` or `cancelled` and clears its runtime solely from
job ID, attempt number, task identity, and transient state. It does not reject acknowledgement
while `worker_active` is true, and the manager exposes no mutation API for the progress or
index-capacity, lease, writer-lock, and pipeline fields in `JobResourceSnapshot`. The state
authority can therefore publish the ADR's acknowledged states while the worker/resources it
claims to have released are still active, and later dispatcher/HTTP work has no supported
way to maintain the canonical resource view. Add manager-owned progress/resource updates and
gate acknowledgement on released worker and resource ownership.

### capability-kind | high | Maintenance jobs receive indexing controls and invalid specs are admitted

`JobSpec` has no cross-field validation and `JobManager.create` accepts every enum
combination, including maintenance operations over vault/code sources and index operations
over the maintenance source. `_capabilities_for_state` then derives capabilities from state
alone, so a maintenance record can be advertised as pausable, cancellable, retryable, or
deletable and can enter indexing lifecycle transitions. The approved research requires
capabilities to depend on job kind and state, with maintenance records read-only. Validate
the operation/source/mode/root matrix in the service domain and compute capabilities from
the validated spec plus state.

### config-overrides | medium | Standard wrapper overrides do not reach the new settings

The public `get_config(overrides)` path forwards overrides into the core `BaseConfig`, whose
schema does not retain RAG-only keys. As a result, `get_config({"job_max_nonterminal": 2})`
still resolves `64`, and the equivalent shutdown-timeout override still resolves `300.0`,
despite the wrapper's documented base/CLI-before-env precedence. The new tests cover only
defaults and environment variables, so this regression is invisible. Retain RAG-only
overrides in `VaultSpecConfigWrapper` (or reject them explicitly) and exercise the public
override path.

### resume-checkpoint-race | high | Pause withdrawal can strand an unwound attempt as running

`JobManager._request_resume_locked` reads `RunControlToken.snapshot().delivered` and may
change `pausing` back to `running` at `src/vaultspec_rag/jobs.py:1337-1367`, but the token
is not actually withdrawn until after persistence at `src/vaultspec_rag/jobs.py:855-872`.
A worker checkpoint can deliver `PauseRequested` between those operations; the later
`request_resume` clears the desired token request even though delivery already committed.
The worker then unwinds while the manager reports `running`, and
`acknowledge_control` ignores its cleanup because `running` is not an acknowledging state.
Make delivery detection and withdrawal one atomic token operation and keep the manager in
`pausing` whenever delivery won the race. Add a deterministic cross-thread test for that
interleaving.

### runtime-ownership-bypass | high | Public runtime helpers can orphan a nonterminal state

`JobManager.attach_runtime` accepts any nonterminal job without requiring `queued` and
without advancing it to `running` at `src/vaultspec_rag/jobs.py:661-681`.
`JobManager.release_runtime` can then clear the owning task and token from a `running` job
without changing its state at `src/vaultspec_rag/jobs.py:760-777`. Once released,
`finish_attempt` and `acknowledge_control` reject the real task by identity, while a later
cancel request enters `cancelling` with no token or task able to acknowledge it. Remove or
internalize these bypasses, or make their state/runtime updates one validated atomic
operation; test owner-task release as well as the existing stale-task rejection.

### maintenance-capabilities | high | Maintenance jobs are exposed as controllable indexing work

The accepted decision requires maintenance records to be read-only, but capability
derivation at `src/vaultspec_rag/jobs.py:1737-1745` considers only lifecycle state.
Consequently a `JobOperation.MAINTENANCE` job created through `JobManager.create` is marked
pausable and cancellable and is accepted by `set_desired_state` exactly like an index job.
Derive capabilities and transition eligibility from both specification and state, and add
coverage proving maintenance records reject lifecycle control.

### idempotency-cardinality | medium | Equivalent-job aliases bypass the manager's memory bound

Every equivalent active create with a fresh idempotency key adds another entry to
`_idempotency` and `_job_idempotency_keys` at `src/vaultspec_rag/jobs.py:538-543` and
`src/vaultspec_rag/jobs.py:1661-1668`. Neither collection has a cardinality or key-length
bound, and all active bindings are serialized on every transition. One active job can thus
accumulate unbounded memory and make the durable state file grow without limit despite the
configured nonterminal bound. Bound retained aliases per job and globally, or avoid binding
new aliases when equivalence rather than original creation supplied the result.

### dedup-root-identity | medium | Equivalent work is compared by raw path spelling

`JobManager._find_equivalent_active_locked` uses direct `JobSpec` equality at
`src/vaultspec_rag/jobs.py:1629-1633`. Equivalent roots with slash, case, relative-segment,
or symlink spelling differences therefore admit separate active jobs, particularly on the
Windows-first platform, defeating the per-root deduplication contract and consuming extra
admission slots. Normalize the project identity once at specification admission and test
equivalent path spellings under the host's path semantics.

### restart-capacity-accounting | medium | Crashed attempts can prevent all restart recovery

`restore_persisted` counts every nonterminal persisted state against the new admission
limit at `src/vaultspec_rag/jobs.py:1200-1208`, even though `running`, `pausing`, and
`cancelling` entries are immediately converted to terminal `interrupted` records at
`src/vaultspec_rag/jobs.py:1237-1252`. Reducing the configured limit below the number of
crashed attempts rejects the entire restore and surfaces none of the required interrupted
history. Apply the capacity check only to queued and paused records that remain
nonterminal, while bounding the converted interrupted records through terminal retention.

### idempotency-retention | high | Unique keys can grow without a manager-level bound

`JobManager.create` records every new idempotency key that deduplicates to retained active
work. The active-job count is bounded, but `_idempotency` and each reverse key set are not,
so repeated externally supplied keys for one active job can grow memory and the durable state
file without limit. Apply an explicit key length and total replay-entry bound whose eviction
cannot remove active jobs.

### pause-withdrawal-race | high | Resume can race a delivered pause signal

`JobManager` observes the control-token snapshot while choosing the `pause_withdrawn`
transition, persists the job as running, and only afterward calls `request_resume`.
`RunControlToken.request_resume` clears a pause even when another thread delivered that pause
between those operations. The worker can then unwind while acknowledgement sees `running`
and ignores it, leaving the logical job without a requeued attempt. Pause withdrawal must be
atomic with the token's delivered state and failure rollback must re-arm the request.

### terminal-durability-rollback | high | Failed persistence can restore an execution that already ended

Control acknowledgement and terminal completion first record that the exact task released
ownership, then restore the pre-transition manager backup when the state-file write fails.
That rollback can expose `running`, `pausing`, or `cancelling` with a task reference after the
worker has already unwound or completed. External execution facts are irreversible: retain
the truthful in-memory state, report degraded durability, and retry persistence rather than
reviving the old attempt.

### persistence-default | high | Manager durability is silently disabled by default

`JobManager.__init__` defaults `state_path` to `None` and stores that value unchanged
(`src/vaultspec_rag/jobs.py:459`, `:473`). Both restore and commit then treat the absent
path as successful in-memory operation (`:1175-1182`, `:1553-1556`). This makes the
canonical manager non-durable unless every future caller remembers to derive and inject a
configured status path, even though the ADR defines one durable service-domain authority
and durable-before-dispatch as an invariant. Resolve the configured managed-state path by
default and retain an explicit opt-out only for intentionally in-memory tests.

### restore-validation | high | Structurally valid corrupt state can restore impossible lifecycle resources

`_parse_persisted_manager_state` validates field types, enum membership, and duplicate IDs,
but it does not validate cross-field lifecycle invariants (`src/vaultspec_rag/jobs.py:1747-1836`).
A syntactically valid file can therefore restore `queued` with desired `paused`, `paused`
with desired `running`, terminal jobs without a finish time, nonterminal jobs with a finish
time, impossible attempt lineage, duplicate equivalent active work, non-finite timestamps,
or an idempotency binding whose signature does not match its referenced job. Dangling
idempotency bindings are silently dropped at `:1260-1266` instead of making the generation
invalid. Validate the complete generation and all job/binding invariants before acquiring
it; reject the whole file on any mismatch.

### rollback-verification | medium | Filesystem tests do not force persistence failure or prove rollback

The new persistence tests cover valid replacement, restart, and malformed JSON, but none
forces `_persist_locked` or `_atomic_replace` to fail after an in-memory mutation. The
concurrent-reader case at `src/vaultspec_rag/tests/integration/test_jobs_registry.py:422-482`
accepts reader-side `PermissionError`; it does not establish writer contention, exhaust the
bounded replace retries, or assert that active jobs, revisions, runtime ownership,
idempotency bindings, and terminal eviction all roll back together. Add a real-filesystem
failure case using a structurally invalid destination path and assert both the returned
structured failure and unchanged manager state, without patches or test doubles.

## Recommendations

- Resolve every high-severity finding before Wave 2 builds dispatch and checkpoints on these
  contracts.
- Add focused real-thread and real-filesystem regressions for each corrected race or bound.

## Resolution

The Wave 1 remediation closed the pause-withdrawal race in the control token, made managed
state durable by default, bounded idempotency-key length and retained aliases, normalized
root identity for active-work deduplication, and validated the complete persisted generation
before recovery. Recovery now counts only jobs that remain nonterminal against admission,
and irreversible worker completion is no longer rolled back to a false live state when a
state-file write fails.

The service domain now rejects invalid and maintenance specifications from the controllable
manager, derives capabilities from both specification and lifecycle state, preserves RAG-only
public configuration overrides, and exposes one atomic runtime claim path. Acknowledgement is
rejected while the exact task is still active or any declared execution resource remains held.
Real-thread and real-filesystem regressions cover these contracts, including reversible
persistence rollback and truthful terminal state after a write failure.

The remaining legacy-authority split is explicitly sequenced for `S16`: production indexing
cannot safely move behind the manager until `S10` through `S15` add cooperative checkpoints
and complete resource instrumentation. The compatibility facade will be modularized first in
`S38` through `S40`; no HTTP or CLI control adapter will be built before manager-owned dispatch.

Verification after remediation completed with Ruff, ty, and BasedPyright clean, 60 focused
unit tests passing, and 15 non-GPU registry integration tests passing. Two GPU subprocess
cases remain intentionally outside this environment because no verified Qdrant test binary is
provisioned.
