---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S09'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# Detect a healthy orphaned daemon via port probe when service.json is absent

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/_service_status.py`

## Description

Both `service_status` and `service_stop` previously returned immediately with
exit 3 / exit 0 respectively when `_read_service_status()` returned None, with
no port probe.

Added two pure helpers in `_service_lifecycle.py`:

- `_orphan_probe_port() -> int` — reads `mcp_port` from `get_config()`, which
  resolves `VAULTSPEC_RAG_PORT` / default 8766. Imported `get_config` at the
  top-level import.
- `_render_orphan_status_json(port, health) -> None` — emits a JSON
  `{"state": "orphaned"}` envelope and raises `typer.Exit(code=4)`.
- `_render_orphan_status_table(port, health) -> None` — prints a Rich table
  with state "orphaned" and raises `typer.Exit(code=4)`.

In `service_status` (status is None branch): calls `_orphan_probe_port()` +
`_health_probe(orphan_port)`; if the probe returns `status: ready`, dispatches
to the appropriate render helper (json_mode or table mode), both of which exit 4.
If the probe returns None, falls through to the existing exit-3 stopped path.

In `service_stop` (status is None branch): same probe; if the port answers,
prints a yellow Panel explaining the orphaned state and raises
`typer.Exit(code=4)`. If the probe returns None, falls through to the existing
"not running" message + `return`.

## Tests

`src/vaultspec_rag/tests/test_service_lifecycle_helpers.py`:

- `TestOrphanRenderExitCodes` — both render helpers raise `typer.Exit(code=4)`.
- `TestOrphanProbePort` — returns a positive int; respects `VAULTSPEC_RAG_PORT`
  override (via `reset_config()`). Uses the `VAULTSPEC_RAG_STATUS_DIR`
  isolation fixture, no mocks.

## Outcome

`ruff check` and `ty check` both clean. 9 unit tests pass (4 directly covering
this step). Live-service orphan detection (actually wiping service.json while
the daemon is running) is covered by W04 integration re-validation.
