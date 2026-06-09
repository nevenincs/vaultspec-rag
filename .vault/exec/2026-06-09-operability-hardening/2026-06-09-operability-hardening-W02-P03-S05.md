---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
step_id: 'S05'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Return non-zero exit when start is blocked by an occupied port

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

In `service_start`, the port-guard branch at the top of the function previously
called `return` after printing the "Port N is already in use" panel, producing
exit code 0. Changed `return` to `raise typer.Exit(code=1)` so a blocked start
is non-zero. The panel message and border_style are unchanged. No other code
paths were touched.

## Outcome

`ruff check` and `ty check` both clean. The change is a single-line swap;
existing tests continue to pass. Live-service coverage is deferred to W04
integration re-validation.

## Notes

Panel kept with `border_style="yellow"` (advisory) rather than "red" to match
existing framing — the port may be occupied by a legitimate prior start rather
than an error.
