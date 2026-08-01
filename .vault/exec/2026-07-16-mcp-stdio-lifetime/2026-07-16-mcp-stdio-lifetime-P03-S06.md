---
tags:
  - '#exec'
  - '#mcp-stdio-lifetime'
date: '2026-07-16'
modified: '2026-07-17'
body_hash: 'sha256:0c48257a0939527217c117d3c97ab33f49d6071bc50c9c9869b65d4691fad60a'
step_id: 'S06'
related:
  - "[[2026-07-16-mcp-stdio-lifetime-plan]]"
---

# Add integration tests: spawn a real parent-intermediary-worker chain, kill the intermediary, assert the worker hard-exits within the bound

## Scope

- `plus a companion EOF-still-primary shutdown test`
- `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`

## Description

- Add `test_stdio_lifetime_e2e.py` (integration): spawn a real
  test-runner -> intermediary -> worker chain, kill the intermediary
  after the grace window, assert the worker hard-exits within the bound
  (the research W2 fires-on-death mandate, in real subprocesses).
- Add the EOF-still-primary companion: the real shim entry point
  (`main()` over piped stdio) exits 0 when stdin closes, watchdog armed.

## Outcome

Both tests pass (~10s); ruff, basedpyright green.

## Notes

First run failed by killing the intermediary INSIDE the grace window -
the watchdog pruned the death as spawn-helper noise by design. The test
now waits out the grace before killing; the interaction is documented in
the test body.
