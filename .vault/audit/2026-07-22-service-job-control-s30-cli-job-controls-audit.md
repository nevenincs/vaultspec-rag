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

# `service-job-control` audit: `s30 cli job controls`

## Scope

Audited `W04.P14.S30`: six command registrations, prefix-to-exact resolution,
JSON exact addressing, optimistic concurrency, structured exits, force mode,
idempotent outcomes, and collection compatibility.

## Findings

### s30-cli-job-controls | medium | malformed revisions disabled concurrency

Resolved. Desired-state commands now require a positive non-boolean integer
revision from exact detail and fail with `invalid_job_resource` before mutation
when the service response is incompatible.

No remaining critical, high, or medium findings. Review status: pass.

## Recommendations

Accept S30. Exercise human and JSON lifecycle behavior against the real server
in S31.
