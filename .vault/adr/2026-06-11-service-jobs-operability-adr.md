---
tags:
  - '#adr'
  - '#service-jobs-operability'
date: '2026-06-11'
related:
  - '[[2026-06-11-service-jobs-operability-research]]'
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-01-service-operability-adr]]'
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-04-12-index-progress-bars-adr]]'
---

# `service-jobs-operability` adr: `operator-grade jobs surface` | (**status:** `accepted`)

## Problem Statement

The current jobs surface is a basic activity dump. It does not work as an operator
interface for current work, failures, queueing, initiators, liveness, or resource context.

The live audit and user review found that `server jobs` is hard to scan, terminal-fragile,
insufficiently filterable, and not actionable.

## Considerations

- Operators usually need running work first, then recent failures, then recent completed
  work.
- Agent users need bounded JSON by default.
- Current records expose source, trigger, phase, timestamps, result, and progress, but not
  enough causality or correlation.
- Watcher activity can bury the job the user cares about.
- Logs and status cannot currently be joined to a job by request or correlation id.

## Constraints

- The in-memory job registry must remain bounded.
- Existing route and CLI users should retain a compatible collection shape where
  possible.
- Additional fields must be real state, not fabricated test-only logic.
- Jobs must not introduce a second source of truth for index progress.

## Implementation

Redesign `server jobs` as an operator view:

- running and queued jobs first by default,
- bounded output by default,
- filters for running, failed, source, trigger, job id, and later project or initiator,
- detail mode for a single job,
- stable bounded JSON output,
- runtime and last-progress age,
- initiator metadata for CLI, MCP, watcher, or service-internal calls,
- project root and request/correlation id where available,
- resource and lock state where feasible.

Status should summarize active jobs. Logs should become filterable by job or request id
once correlation exists.

## Rationale

The service already records activity, but users need an operational model rather than a
history dump. The jobs part of the service-observability ADR is superseded by an
operator-first contract.

## Consequences

The job model will grow. Tests must focus on real behavior and should verify ordering,
filtering, bounded defaults, liveness fields, and JSON stability.

Manual CLI testing is mandatory because table layout and scanability cannot be validated
by unit tests alone.

## Codification candidates

- **Rule slug:** `operator-views-default-current-state`.
  **Rule:** CLI operator views must default to current actionable state, not full history.

- **Rule slug:** `long-running-work-has-correlation`.
  **Rule:** Long-running service work must expose a stable job id, initiator, liveness,
  and correlation fields suitable for joining status, jobs, and logs.
