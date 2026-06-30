---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Added `_write_machine_discovery` (atomic `.tmp` + `os.replace`, best-effort, debug-logged on failure) and called it from `_heartbeat_tick_sync` after the STATUS_DIR write, mirroring the same versioned payload to the machine-global pointer.
- Extended `_unlink_status_file_silently` to also remove the machine-global pointer on shutdown, so a stopped service leaves neither discovery file behind.

## Outcome

The daemon now advertises its coordinates at the STATUS_DIR-independent pointer on every heartbeat and cleans it on shutdown; the STATUS_DIR file and the lock authority are unchanged.

## Notes

The pointer write is best-effort (a failure never breaks the heartbeat); the STATUS_DIR file still describes the service and the OS lock remains the singleton authority.
