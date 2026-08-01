---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:16bafcc56c5e204f1a48c6982c278db74793860b8405fbeafad837fb728a9e1a'
step_id: 'S04'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Add a top-level entrypoint os.\_exit backstop on any startup exception escaping uvicorn.run

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Add `import os` to the daemon entrypoint module.
- Track a `daemon_exit_code` around `uvicorn.run`, set to 1 by an `except`
  branch when the run raises.
- In the entrypoint `finally`, after component close and log-capture drain,
  force `os._exit` for the standalone daemon (gated on `_daemon_process`),
  preserving the log-drain-contract raise for the in-process embedded-reuse
  host.

## Outcome

A startup failure that escapes `uvicorn.run` without the lifespan's own
`os._exit` firing - the port-bind sibling, or any error uvicorn surfaces before
the lifespan runs - now forces a prompt daemon exit instead of a wedged
interpreter shutdown. ruff, ty, basedpyright, and the complexity gate clean.
Committed in `57bdee8f`.

## Notes

Covers the one failure class the lifespan guard cannot: a failed port bind never
reaches the lifespan, so the exit backstop must live at the entrypoint. Off the
standalone daemon this is inert and the embedded-reuse drain contract is
unchanged.
