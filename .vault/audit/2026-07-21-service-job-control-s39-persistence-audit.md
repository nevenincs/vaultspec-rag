---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-W01-P18-S39]]"
---

# `service-job-control` audit: `S39 persistence boundary`

## Scope

Audited the S39 extraction of the v1 job-state codec and atomic filesystem
store, the `JobManager` delegation boundary, write-failure phase handling,
on-disk compatibility, and real persistence integration coverage.

## Findings

### s39-persistence-boundary | high | Atomic replacement did not make the directory entry durable

The initial extraction fsynced the temporary file before `os.replace`, but did
not sync the POSIX parent directory or request write-through replacement on
Windows. The revision now syncs newly created POSIX directory entries and the
destination parent after replacement. Windows uses `MoveFileExW` with
replace-existing and write-through flags plus bounded access-denied and
sharing-violation retries.

### s39-persistence-boundary | medium | Codec validation accepted ambiguous version and timestamp values

The initial decoder accepted boolean and integral-float spellings of version 1
and did not reject impossible control and finish timestamp relationships. The
revision requires an integer version and validates request/acknowledgement,
attempt start/finish, and final state-change ordering.

### s39-persistence-boundary | high | Strict acknowledgement validation broke legacy v1 start-paused state

The committed v1 writer represented a job created paused with an acknowledgement
timestamp but no request timestamp. The revision now normalizes only that exact
first-attempt, unstarted, unfinished legacy shape when acknowledgement, creation,
and state-change times are equal. Every other acknowledgement without a request
remains invalid. A real-file integration test verifies restoration and canonical
migration.

### s39-persistence-boundary | medium | Post-publication filesystem failure cannot be safely forced on this host

Real Windows integration coverage exercises successful write-through replacement,
concurrent readers, and definitely-unpublished access-denied rollback. A failure
after publication cannot be induced safely without prohibited doubles. The
post-publication create, retry, pause, cancel, dirty-state, and outcome-identity
branches therefore received explicit static and type review; the independent
review accepted this platform limitation.

## Recommendations

Keep commit-phase failures explicit: roll memory back only when publication is
known not to have happened, and retain a dirty in-memory generation whenever the
new file may be visible. Preserve the narrow legacy v1 normalization until the v1
compatibility window is intentionally retired.

## Status

PASS. The final independent re-review found no Critical or High findings. Ruff,
ty, and strict BasedPyright passed, and the focused verification completed with
75 passing tests.
