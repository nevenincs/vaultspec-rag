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

# `service-job-control` audit: `s26 http job crud tests`

## Scope

Audited `W04.P12.S26`: real-ASGI authentication, canonical create and detail,
exact mutations, revisions, idempotency, capacity, force rejection, retry
lineage, deletion conflicts, `Location` headers, and test integrity.

## Findings

### s26-http-job-crud-tests | medium | mutation prefixes were untested

Resolved. Desired-state update, retry, and deletion now each reject a shortened
job identifier with `404`, alongside exact-detail enforcement.

### s26-http-job-crud-tests | medium | desired-state replay was untested

Resolved. Repeating the terminal desired state with the now-stale original
revision returns structured `already_satisfied` success without changing the
job identity, revision, or state.

### s26-http-job-crud-tests | medium | lifecycle state used shared persistence

Resolved. The real-ASGI fixture now binds every route test to a temporary
manager status directory, clears the singleton before and after use, and
restores process configuration.

## Recommendations

Accept S26 after the required corrections. Continue client transport under
S27.
