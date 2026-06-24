---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S05'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Add a storage-lock probe distinguishing a live holder from a dead owner

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Added the managed-Qdrant identity sidecar contract to `_resolve.py`: a `QdrantIdentity`
  record (storage path, version, owner pid, port), `qdrant_identity_path()`, and a tolerant
  `read_qdrant_identity()` that returns None on absence/corruption.
- Added cross-platform `pid_alive(pid)` (Windows `OpenProcess`+`GetExitCodeProcess`; POSIX
  `os.kill(pid, 0)`) so a live storage owner can be told from a dead one.

## Outcome

The "is the storage owner live or dead" signal exists: the owner pid comes from the identity
sidecar and `pid_alive` resolves its liveness. `ruff` and `ty` pass; verified by the S07 test
(self alive, never-used pid dead).

## Notes

The step's "storage-lock probe" is realized as owner-pid liveness against the identity record
rather than poking RocksDB lock files directly: RocksDB exposes no portable lock-query, and
the owner-pid signal is what cleanly distinguishes a live holder from a dead one. The identity
WRITER lands in S08 (W02.P03); this reader degrades to "no record" until then. No blockers.
