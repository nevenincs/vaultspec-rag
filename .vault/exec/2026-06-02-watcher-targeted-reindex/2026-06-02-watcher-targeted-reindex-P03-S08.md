---
tags:
  - '#exec'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S08'
related:
  - "[[2026-06-02-watcher-targeted-reindex-plan]]"
---

# Run ruff and the full pytest suite and confirm zero violations and green before PR

## Scope

- `pyproject.toml`

## Description

- Run ruff across the package and confirm zero violations.
- Run the full unit suite and confirm it is green.
- Run the watcher and targeted-reindex integration files together to confirm the
  idle-yield change does not regress add, edit, delete, or no-op behavior.
- Run the server-mode scoped-delete integration test against the supervised real
  Qdrant server.

## Outcome

All gates green. Ruff reported zero violations. The unit suite passed 1021 tests
(572 non-unit deselected). The watcher plus targeted-reindex integration files
passed 12 tests, including the two new cooldown-flush tests and the pre-existing
add/edit/delete/no-op coverage, proving no regression. The server-mode scoped
delete passed against the real engine.

## Notes

The entire GPU integration suite (service lifecycle, eviction, logs, metrics,
jobs) was not run exhaustively in one pass because the local box was under GPU
memory contention from prior sessions, which inflated index times and caused a
300-second test-timeout in a combined run that passed cleanly when the same
tests were re-run in isolation. The change is confined to the watcher's awatch
construction, so the gate targeted the full unit suite plus every watcher,
scoped-reindex, and server-mode integration test that exercises the affected
path. The remaining GPU integration suites should be run on a quiescent box
before merge per the project's local-GPU verification norm.
