---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ebb379448b55ae2831217e8759fcfd5838d204a8493683ede6da51f2350284a2'
step_id: 'S24'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Render pause and resume as success only when ok is true and the canonical quiesce block carries the requested achieved state, preserving exact unsafe status, error, retryable, message, and quiesce evidence in human and JSON failures

## Scope

- `src/vaultspec_rag/cli/_service_quiesce.py`

## Description

Require the service-owned `ok: true` response to carry the exact achieved
canonical state before the CLI exits successfully. Preserve a complete,
structured service failure verbatim in both human and JSON output.

## Outcome

Accepted for S24 after `de91373f` removes the in-memory source rewrite and AST
inspection. `0e7cce89` makes pause and resume accept only `quiesced` and
`running`, respectively, after decoding the route envelope. The reported
CPU-only proof includes ten focused CLI and adapter tests, with the checked-in
real loopback cases covering achieved and idempotent transitions, a real
transition conflict, and absence of discovery.

## Notes

The successful wrong-state envelope is not emitted by the current truthful
route. Its exact-state condition is static, unexercised defense-in-depth under
the amended W03 rule; do not manufacture a response or inspect mutated source
to prove it. The reported focused test run started no daemon lifespan, GPU, or
Qdrant process.
