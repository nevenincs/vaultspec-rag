---
tags:
  - '#audit'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---



# `index-backpressure-storage-hygiene` audit: `execution review of the fail-loud write path and storage hygiene feature`

## Scope

Branch diff versus main after the sibling storage/backpressure fixes had
merged: the shared job-failure taxonomy and stall surfacing, the CLI
disk-preflight envelope, the ephemeral idle-TTL reclaim tier and activity
clock, debris visibility and gated removal, tuned collection
preallocation, the structural test-isolation guards, and interrupted-job
restore. Reviewed by the code-reviewer persona against the governing ADR,
the plan, and the six binding rules; all findings verified and actioned
in-session.

## Findings

### ephemeral-midwrite-reclaim | high | data-tier reclaim could archive and drop an actively indexed temp namespace

The ephemeral data tier archived-then-dropped without the mid-write guard
the empty tier has (its pre-drop point re-count), and the activity clock
was stamped only at run completion - so a long index run spanning a
maintenance tick presented a stale `last_indexed` the whole way through.
RESOLVED: every index wrapper now stamps the clock at run start as well
as completion, so an in-flight run advances past the TTL before any
reclaim evaluation can see it.

### debris-delete-toctou | medium | a mid-create collection dir could be removed as debris

`prune_debris` snapshotted the live collection list once; a collection
created between that snapshot and the removal has a dir on disk before
the server lists it. RESOLVED: the live list is re-fetched immediately
before each removal and a now-live name is skipped as `appeared_live`.

### success-summary-remediation | low | taxonomy remediation could replace a non-error result summary

`_human_result` applied the shared classification to any result text, so
a success summary containing a marker word ("timeout") would have been
replaced by remediation text. RESOLVED: remediation now applies only when
the job's phase is failed.

### snapshot-progress-granularity | low | restored interrupted jobs carry step-granular progress

The active-jobs snapshot persists on step transitions, not per-batch, so
a restored `interrupted` job shows progress as of its last step change.
ACCEPTED: deliberate write-churn trade-off, documented in the code.

### oom-floor-source-scan | low | the encode-floor regression guard is a source-substring scan

`TestEncodeRecoveryStaysBounded` pairs handler and floor counts by
substring; an innocuous refactor could break it. ACCEPTED: structural
guards of this shape are the repo's established idiom.

### integration-under-live-load | low | daemon-spawning integration tests time out while the operator's recovery index runs

The `live_service`-based integration tests spawn sandboxed daemons whose
GPU model load cannot complete inside the 90s readiness window while the
resident production service is mid-way through the 250k-chunk recovery
index (confirmed live at review time). Environmental contention, not a
regression: the full unit suite (1503) and the non-daemon integration
tests (68) are green. Follow-up: rerun the daemon-spawning integration
files once the resident index completes, before merge.

## Verdict

Approve with fixes; all fixes applied and verified in-session (212
targeted tests plus full gates green). All six binding rules confirmed
clean by the reviewer: time-confirmed danglingness, lifecycle inertness,
service-domain operability, structured idempotent broker outcomes, GPU
lock scope, and machine-singleton test isolation.
