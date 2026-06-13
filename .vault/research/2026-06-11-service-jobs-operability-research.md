---
tags:
  - '#research'
  - '#service-jobs-operability'
date: '2026-06-11'
modified: '2026-06-11'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-01-service-operability-adr]]'
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-04-12-index-progress-bars-adr]]'
---

# `service-jobs-operability` research: `operator-grade jobs surface`

This research grounds the decision to redesign `server jobs` from a basic history dump
into an actionable operator interface.

## Findings

### R1. The current jobs output is not an operator interface

`server jobs --json --limit 5` returns recent activity records, but the records are
history-oriented rather than operational. Recent watcher jobs can dominate the view even
when the user wants to know what is running now, what failed, or what is blocking search.

The table form is also fragile in terminal contexts and does not efficiently expose the
current job state.

### R2. The job model lacks causality and correlation

Current records expose basic source, trigger, phase, timestamps, result, and progress.
They do not answer:

- which CLI invocation, MCP tool, watcher, or service component initiated the work,
- which project root the work belongs to,
- which request or log lines correspond to the job,
- whether a wrapper is currently waiting,
- whether memory/GPU/Qdrant pressure is relevant,
- whether a stalled-looking progress count means dead, blocked, or busy.

### R3. Running-first and filtered views are required

The default view should prioritize actionable state:

1. running or queued jobs,
1. recent failed jobs,
1. recent completed jobs.

Filtering should include running/failed, source, trigger, job id, and later initiator or
project root. Full history should require an explicit `--all` or high limit.

### R4. Jobs should cross-reference status and logs

The status surface should summarize active jobs. Job detail should expose request or log
correlation ids. Logs should be filterable by job/request id when correlation exists.

Without these links, users must manually inspect raw logs and unrelated route activity.

### R5. Recommended direction

The ADR should supersede the jobs portion of `service-observability` and extend
`service-operability` by making job visibility part of the operator contract.

Implementation should add:

- bounded defaults,
- running-first sorting,
- filters,
- detail mode,
- initiator metadata,
- project root,
- correlation id,
- runtime and last-progress age,
- resource/liveness state where feasible,
- stable JSON for agent consumption.
