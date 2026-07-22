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

# `service-job-control` audit: `s32 reindex mcp compatibility`

## Scope

Audited `W04.P15.S32`: live MCP registration, refresh schemas and annotations,
job-control exclusion, real reindex compatibility mapping, watcher opt-out,
and test isolation.

## Findings

No review findings. Review status: pass.

During verification, the compatibility route exposed an automatic watcher
warm despite the configured watcher opt-out. This was corrected before review;
the guard now precedes root resolution, locking, registry access, and task
creation.

## Recommendations

Accept S32. Preserve the exact five-tool MCP boundary and keep destructive
rebuild and lifecycle controls outside the agent-facing surface.
