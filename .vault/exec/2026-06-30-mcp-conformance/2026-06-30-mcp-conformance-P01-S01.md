---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Add a machine-singleton discovery resolver that returns the live service port and token from read_machine_discovery validated by machine_lock_live_holder and heartbeat staleness

## Scope

- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

Added `_machine_service_resolution()` to the import-light discovery module so the one resident machine service is located through machine-global state every consumer shares regardless of its own status directory.

## Outcome

The resolver probes `machine_lock_live_holder()` for liveness (the OS advisory lock, which the OS releases when the holder dies) and reads the machine-global pointer via `read_machine_discovery()` for the address. The payload is accepted only when a live holder exists and its heartbeat is fresh within the payload's own `stale_after_s` window (`_discovery_is_stale`, falling back to a 60s default); a `_coerce_port` helper validates the port. An orphaned pointer (dead pid, days-old heartbeat) is therefore treated as absence. Verified by real-behavior tests that acquire the actual lock and write real pointer files - no mocks.

## Notes

ty, basedpyright, ruff, and the complexity gate are all green on the change.
