---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S08'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add a warming branch to \_explicit_port_state and the port-only renderer (pid and since rendering, distinct exit code) and make the already-owns-this-machine start message say warming when the sidecar phase says so

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- `_compute_state` gains a phase parameter: a live, identity-confirmed pid with phase warming reports state warming (exit 5) before the silent-port and stale-heartbeat crash branches.
- `_explicit_port_state` gains phase/pid_alive: silent port + live pid + warming reports warming (exit 5) instead of stopped.
- The already-owns-this-machine start guard reads the sidecar phase and says the holder is warming (adds holder_phase to the --json failure envelope).
- `_status_next_action` returns a retry-shortly hint for warming instead of pointing at crash logs.

## Outcome

Committed as 2ed542d. ruff, basedpyright, ty clean.

## Notes

The port-only renderer (no service.json at all) keeps the 3-way collapse: with no sidecar there is no phase evidence to distinguish warming from stopped.
