---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S08'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Write a machine-local qdrant identity sidecar on bring-up (storage, version, owner token)

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Added `write_qdrant_identity(...)` to `_resolve.py`: atomically writes the managed-Qdrant
  identity sidecar (storage path, version, owner pid, port) via a `.tmp` sibling + `os.replace`
  to `qdrant_identity_path()` (machine-global, alongside the storage).
- Wired the writer into `start_supervised_from_config`: after a freshly-spawned server is
  ready, it records storage, the live `server_version()`, `os.getpid()` as owner, and the port.

## Outcome

A managed Qdrant now leaves a local-trust identity record so a later start can confirm
ownership and learn the owner pid (the signal the attach gate and orphan classification key
on). `ruff` and `ty` pass; verified by the S10 round-trip test.

## Notes

The writer runs only on the spawn path (an attach reuses an existing record). No blockers.
