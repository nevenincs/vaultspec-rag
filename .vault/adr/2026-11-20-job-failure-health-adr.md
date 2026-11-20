---
tags:
  - '#adr'
  - '#job-failure-health'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:c1a36866cd50035f26ed4ff945454a567982668cdf2b7f2709e178247729fd24'
related:
  - "[[2026-09-23-status-messages-adr]]"
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-25-service-release-compatibility-adr]]"
  - '[[2026-11-20-job-failure-health-reference]]'
  - '[[2026-07-22-service-health-client-hardening-adr]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
---

# `job-failure-health` adr: `per-project failing outcomes decide job-failure health` | (**status:** `proposed`)

## Problem Statement

Service health degrades on one failed indexing job for as long as the daemon runs. The
service selects the single newest non-refusal failure across every project
(`src/vaultspec_rag/server/_lifespan.py:1278`) and degrades with `job_failed` until a
later success lands on the same project and source
(`src/vaultspec_rag/server/_lifespan.py:1204`, `:1347-1358`). The only other bound is
the process generation (`src/vaultspec_rag/server/_lifespan.py:1177`). Four defects
follow:

- A failure never ages out within a generation. On a live daemon, one failed job kept
  health `degraded` for 16 hours while other jobs ran clean. The registry held 69 failed
  jobs.
- A later cancelled or interrupted run on the same project leaves the failure in place,
  with nothing to say whether that project is still broken.
- Only the newest failure is examined. An older unresolved failure on another project is
  hidden, and a resolved newest failure can hide it too.
- The reported `jobs.last_failed` names one job, so the operator reads "the latest
  indexing job failed" when the real condition is per project.

A decision is needed because the health payload shape and the meaning of `job_failed`
are a contract that the CLI status surfaces render
(`src/vaultspec_rag/cli/_status_labels.py:474`, `src/vaultspec_rag/cli/_status_render.py:814`).

## Considerations

- Health, status and jobs diagnostics are service-domain behaviour; CLI and MCP adapt
  (`2026-06-11-service-status-convergence-adr`, `2026-09-23-status-messages-adr`).
- `job_failed` is a `DegradationReason` member that the service emits and the CLI
  renders (`2026-09-23-status-messages-adr`). A degraded service stays `RUNNING`, exit 0,
  so degradation is a signal, not an outage.
- The service already bounds failures to the current generation and excludes
  `full_reindex_required` refusals and `interrupted` runs, for reasons stated at
  `src/vaultspec_rag/server/_lifespan.py:1268-1277`. Those exclusions stay.
- A cancelled run is an operator or watcher decision. It says nothing about whether the
  project's index can be built.
- Watched projects re-index on change, so an unresolved failure on an active project is
  normally retried within minutes. A failure that nothing retries for an hour usually
  belongs to a project that nobody is working in.
- Terminal history is bounded and operator-deletable
  (`2026-07-21-service-job-control-adr`). Deleting a terminal record is the existing
  acknowledgement path.
- `jobs` in the typed health model is an open mapping
  (`src/vaultspec_rag/operator_state/_models.py:136`), so its keys can change without a
  model or schema change.
- Client and daemon are expected to be the same release; a mismatch is detected and
  reported (`2026-07-25-service-release-compatibility-adr`).

## Considered options

- **Keep the newest-failure selector and add an age limit.** Fixes the 16-hour case. It
  still hides older failures on other projects and still lets a cancelled run leave
  the newest failure standing. Rejected.
- **Keep the selector and let any later terminal run on the project clear it.** A
  cancelled or interrupted run would then claim a recovery it never showed. Rejected.
- **Fold the latest decisive outcome per project and source, list the failing ones, and
  degrade only on recent failures (chosen).** Every unresolved failure is visible, a
  cancelled run neither clears nor causes a failure, and a stale failure stops degrading
  without disappearing.
- **Degrade on every unresolved per-project failure for the whole generation.** Honest
  about index state, but it reproduces the 16-hour symptom for any project that is
  never re-run. Rejected.
- **Make the window configurable.** No calibration evidence exists to act on. Rejected
  for now; the window is a code constant.

## Constraints

- The service computes the failing set once, in the health route's job rollup. The CLI
  renders it and derives nothing. MCP gains no new surface from this record. Any later
  MCP health surface reads the same service field.
- The key is the normalized project root plus the source (`vault`, `code`, `document`),
  with the same root normalization the current supersession check uses
  (`src/vaultspec_rag/server/_lifespan.py:1230-1232`).
- Decisive outcomes are `succeeded` and `failed`. A `failed` record with error kind
  `full_reindex_required` is not decisive. `cancelled`, `interrupted` and `superseded`
  records are not decisive. Non-decisive records neither clear nor create a failure.
- A key is failing when its newest decisive outcome is a failure. Ordering uses the
  existing record update stamp (`src/vaultspec_rag/server/_routes_jobs.py:209`).
- A failing key degrades health only while its failure finished inside the current
  generation and inside the degradation window. Outside either bound it stays listed
  with `degrading: false`.
- The degradation window is a code constant. Its initial value of 3600 seconds is an
  implementation hypothesis. The shape is binding: recent unresolved failures degrade,
  older ones are listed.
- The reported list is bounded: at most 5 entries, degrading entries first, newest first
  within each group, with total counts.
- `jobs.last_failed` is removed in the same change. No alias stays behind.
- No version or schema bump. The storage schema (`src/vaultspec_rag/store_schema.py:70`),
  the job-state file version (`src/vaultspec_rag/job_persistence.py:63`), the discovery
  schema and the package version are untouched. The change is a key change inside the
  open `jobs` mapping of `/health`.
- The `job_failed` code value stays the same. Only its label and detail text change.
- This record does not reopen `2026-07-22-service-health-client-hardening-adr`. That
  record governs how clients call `/health`, not what the payload reports.

## Implementation

We will replace the newest-failure selector with a per-project fold over job history.
The fold reports every failing project and source, and degrades health only for failures
that are recent and belong to the current generation.

**Service fold.** In `src/vaultspec_rag/server/_lifespan.py`, one function folds the
job records once. For each key it keeps the newest decisive outcome, then returns the
failing keys. Each entry carries `id`, `project_root`, `source`, `error_kind`,
`finished_at` and `degrading`. `degrading` is true when the failure finished inside the
current generation (`_failure_belongs_to_this_generation`, kept) and its age is within
the window. The fold is linear in the record count.

- Delete `_failure_was_superseded` (`:1204`). The fold replaces it.
- Delete `_failed_job_health` (`:1112`) and the `last_failed` selection (`:1278-1285`).
- Keep `_latest_job_record` (`:1098`); the resilience rollup still uses it.

**Health payload.** `_jobs_health` (`:1260`) replaces `jobs.last_failed` with
`jobs.failing`, shaped `{"total": int, "degrading": int, "entries": [...]}` and bounded
as the Constraints state. It appends one `JOB_FAILED` degradation when `degrading` is
non-zero. The detail names the count and the first degrading entry's project root,
source and error kind, for example `2 project index runs failed: /w/demo (code:
cuda_oom) and 1 more`. The bound and naming follow the stale-roots precedent at
`:1363`.

**Vocabulary.** In `src/vaultspec_rag/operator_state/_service.py:171`, the
`JOB_FAILED` label changes from "the latest indexing job failed" to "a project's latest
index run failed". The member and its value `job_failed` stay.

**CLI adapters.** In `src/vaultspec_rag/cli/_status_labels.py`,
`_last_failed_record`, `_last_failure_job_id`, `_last_failure_label` and
`_failed_job_finding` (`:409-496`) read `jobs.failing.entries`. Collapse them into the
fewest readers that serve both callers. The finding names the first degrading entry,
counts the rest, and keeps the per-project rebuild remedy or the `server logs --job-id`
command. `_HISTORICAL_FAMILIES` (`:392`) stays: the CLI promotes `job_failed` only when
the service emitted it. `_failure_followup` in
`src/vaultspec_rag/cli/_status_render.py:814` names the first listed entry, degrading or
not, when the degraded block did not already name it.

**Files to change.**

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/operator_state/_service.py`
- `src/vaultspec_rag/cli/_status_labels.py`
- `src/vaultspec_rag/cli/_status_render.py`
- `docs/service-mode.md`: describe per-project failing entries and the window.
- Tests: `src/vaultspec_rag/tests/test_health_degraded_clears.py`,
  `src/vaultspec_rag/tests/test_cli_service_status.py`,
  `src/vaultspec_rag/tests/test_job_manager_degradation.py`,
  `src/vaultspec_rag/tests/integration/test_service_jobs_resilience.py`.

**Guard tests.** Each must be shown to fail on its named assertion when the guard is
broken:

- A later cancelled run on the same key does not clear a failure.
- An older failure on project A stays listed and degrading when a newer failure on
  project B is resolved by a success.
- A failure older than the window is listed with `degrading: false` and does not degrade
  health.
- A `full_reindex_required` refusal never appears in `failing`.

## Rationale

The per-project fold is the only option that fixes all four defects. Visibility comes
from folding every key instead of choosing one record. Correct clearing comes from
counting only decisive outcomes: a success proves recovery, a cancellation proves
nothing. Bounded duration comes from splitting "failing" from "degrading". The window
caps how long a failure can hold the health verdict. The list keeps an unresolved
failure visible after that, so the operator never loses the fact.

A pure age limit fails the visibility test. Clearing on any terminal run fails the
honesty test. Degrading for the whole generation fails the duration test, which is the
reported symptom. A window over a list passes all three, and it costs one constant.

## Consequences

- Health stops reading `degraded` for hours on one stale failure. After the window, the
  failure moves to a listed, non-degrading entry with its remediation.
- Every failing project is visible at once, bounded to five named entries plus counts.
- A failure on a project that nobody re-runs stays listed, without degrading, until a
  later success on that key or deletion of the failed record.
- JSON consumers of `jobs.last_failed` break. Mixed client and daemon releases are
  already flagged by the release-compatibility check.
- The window will be wrong in some direction until observed. Too short hides a live
  fault from the verdict, though the list still shows it. Too long reproduces the
  symptom in a smaller form. Revisit the numeral with operator evidence, not the shape.
- Reconsider this record if health gains a per-project verdict. A per-project index
  failure would then belong there rather than in the service-wide verdict.
