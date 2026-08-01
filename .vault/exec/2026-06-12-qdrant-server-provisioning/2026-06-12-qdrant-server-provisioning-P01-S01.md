---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
body_hash: 'sha256:13a0b9ff4527761ef6c583019055de51615ed770ecc7841e670551e90de4e122'
step_id: 'S01'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Create qdrant_runtime constants module with the pinned server version and the committed per-asset SHA256 map, plus config knobs for server toggle, port, binary, and storage dir

## Scope

- `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `src/vaultspec_rag/config.py`

## Description

- Add `qdrant_runtime/_constants.py`: pin `QDRANT_SERVER_VERSION = "1.18.2"`, commit SHA256
  digests for all six upstream release assets (transcribed from the v1.18.2 release JSON),
  define the allowed download host set, the `QdrantProvisionAction` sync vocabulary, and the
  `ProvisionReport` / `ResolvedBinary` / `QdrantRuntimeState` report dataclasses.
- Add four config knobs to `config.py`: `qdrant_server` (bool, default off), `qdrant_port`
  (default 8765), `qdrant_binary` (operator escape hatch), `qdrant_storage_dir`
  (shared multi-root storage default), each with its `VAULTSPEC_RAG_*` env var and
  override-map entry.

## Outcome

Constants module and config knobs in place; `TestPinTable` and `TestConfigKnobs` unit
tests green (digest hex shape, env overrides, defaults).

## Notes

None.
