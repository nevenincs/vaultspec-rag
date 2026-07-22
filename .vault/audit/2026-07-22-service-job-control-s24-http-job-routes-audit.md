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

# `service-job-control` audit: `s24 http job routes`

## Scope

Audited `W04.P12.S24`: authenticated canonical job creation, exact detail,
desired-state mutation, retry, terminal deletion, `/reindex` compatibility,
production dispatch activation, structured outcomes, and focused real-ASGI
coverage.

## Findings

### s24-http-job-routes | high | create and retry returned stale snapshots

Resolved. Successful dispatch now replaces the pre-dispatch job in the
structured create or retry outcome with the manager's post-dispatch snapshot,
so state and revision are current.

### s24-http-job-routes | high | code policy validation followed admission

Resolved. Create and retry validate the real code-index policy before the
manager durably admits work. Activation no longer performs a fallible policy
check after admission.

### s24-http-job-routes | medium | malformed reindex types escaped validation

Resolved. The compatibility adapter type-checks the `type` field before set
membership and returns `400 invalid_job_spec` for strings and non-string JSON
values outside the accepted vocabulary.

## Recommendations

Accept S24 after the required corrections. Continue health rollups under S25
and the comprehensive authenticated route matrix under S26.
