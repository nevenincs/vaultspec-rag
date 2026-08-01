---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8a17dc45d986ce5778785f295c5f26abf57b583d4d94325cafa50d2199fb3659'
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

### s24-http-job-routes | high | durable mutations blocked the ASGI event loop

Resolved. Create, desired-state, retry, delete, and `/reindex` now await real
registry persistence through the existing AnyIO worker boundary. Asynchronous
dispatch creates its task on the owning event loop but holds execution behind a
gate until runtime ownership is durably published, preserving
durable-before-dispatch ordering. Activation bookkeeping and unstarted failure
publication also run off-loop.

A real-ASGI regression keeps a 32 MiB terminal result in the production durable
registry, exercises all four canonical mutation methods, and proves each write
overlaps an independent `401` response. It imports the production manager,
routes, persistence, and ASGI application without test doubles.

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

Accept S24 after the required corrections and the event-loop responsiveness
follow-up. Continue health rollups under S25 and the comprehensive authenticated
route matrix under S26.
