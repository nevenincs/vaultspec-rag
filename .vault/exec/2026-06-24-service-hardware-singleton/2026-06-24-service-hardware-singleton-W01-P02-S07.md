---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S07'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Unit-test the holder and orphan detection primitives

## Scope

- `src/vaultspec_rag/tests/test_qdrant_detection.py`

## Description

- Authored `test_qdrant_detection.py` (no mocks, no GPU): probes a real stdlib
  `ThreadingHTTPServer` on an ephemeral loopback port (and a dead port) for the endpoint
  probe; checks `pid_alive` against this process and a never-used pid; and exercises
  `classify_qdrant_state` across all five states with constructed inputs.

## Outcome

8 tests pass in ~1.7s, no GPU. The detection primitives are verified end to end. `ruff` and
`ty` pass.

## Notes

Removed a `log_message` override on the fake handler (its signature was an invalid override
under the type checker); the default stderr access log is captured by pytest and harmless.
Free non-default ports (599xx / ephemeral) keep the test off the real Qdrant on 8765. No
blockers.
