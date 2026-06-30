---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Define the prefix-to-root manifest schema and its on-disk location under the managed service directory

## Scope

- `src/vaultspec_rag/registry.py`

## Description

- Add a frozen `ManifestEntry` dataclass (prefix, root, backend, last_indexed).
- Resolve the manifest path under the managed service directory via the `VAULTSPEC_RAG_STATUS_DIR` env seam, mirroring the local-only marker convention in `config.py`.
- Persist atomically through a `.tmp` sibling plus `os.replace` under a process `RLock` so concurrent indexers do not clobber each other.

## Outcome

Manifest schema and on-disk location implemented and unit-tested (round-trip, atomic write leaves no `.tmp` sibling). Backend status is green for this step: ruff, ruff format, and basedpyright all clean.

## Notes

Placed in a dedicated `src/vaultspec_rag/storage_manifest.py` module rather than `registry.py` (the plan's scope hint): `registry.py` is only the `ServiceRegistry` singleton holder, so a dedicated module keeps the manifest cohesive and avoids conflating concerns. The prefix is derived from `root_collection_prefix` so it matches the server-mode collection namespace exactly.
