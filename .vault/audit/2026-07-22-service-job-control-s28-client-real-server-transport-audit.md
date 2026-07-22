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

# `service-job-control` audit: `s28 client real server transport`

## Scope

Audited `W04.P13.S28`: real loopback transport behavior for typed job create,
detail, desired-state, retry, and delete operations; structured conflict
preservation; test isolation; and prohibited-test-double compliance.

## Findings

### s28-client-real-server-transport | medium | retry transport was not covered

Resolved. The real-server lifecycle now calls the typed retry operation and
asserts the accepted outcome, retry code, exact new identifier, and parent
linkage.

### s28-client-real-server-transport | medium | cleanup assertions could leak globals

Resolved. Startup and shutdown now live inside an outer guaranteed-cleanup
boundary. Job state, token, status environment, and configuration caches are
restored before the server-stopped assertion can fail.

### s28-client-real-server-transport | medium | context manager used a deprecated return annotation

Resolved. The real-server fixture now declares its generator return directly,
so Python 3.13-aware BasedPyright validation passes without suppressions.

## Recommendations

Accept S28. Keep the single real-server lifecycle as the transport contract for
subsequent CLI and MCP adapter tests.
