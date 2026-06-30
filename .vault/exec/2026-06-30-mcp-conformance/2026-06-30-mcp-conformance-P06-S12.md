---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S12'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Add real-behavior tests for cross-status-directory discovery resolution and staleness rejection

## Scope

- `src/vaultspec_rag/tests/test_machine_discovery_resolution.py`

## Description

Real-behavior discovery resolution tests.

## Outcome

`test_machine_discovery_resolution` exercises a real OS lock and real pointer files across absence, fresh resolution, staleness rejection, authority over a foreign status file, and the status-dir fallback - cross-status-directory resolution proven without mocks.

## Notes

Five tests, all green.
