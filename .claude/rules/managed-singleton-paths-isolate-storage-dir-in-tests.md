---
name: managed-singleton-paths-isolate-storage-dir-in-tests
trigger: always_on
---

# Managed-singleton paths isolate the storage dir in tests

## Rule

Any test or caller that exercises `write_qdrant_identity` or
`acquire_machine_lock` must set `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp path
before invoking it, because the machine-global identity sidecar and the
machine-scoped service lock both derive their location from that env knob, not
from `VAULTSPEC_RAG_STATUS_DIR`.

## Why

The `2026-06-24-service-hardware-singleton-audit` recorded a leaked identity
sidecar written to the real machine-global managed dir: an early test iteration
isolated state with `config_override`, which does not reach
`qdrant_storage_dir`, so the writer targeted the operator's real
`~/.vaultspec-rag/qdrant-server/` instead of a temp dir. The machine lock shares
that parent (`machine_lock_path()` is `storage.parent / "service.lock"`), so an
unisolated test would also acquire the real machine singleton and collide with a
live service or a sibling test. The constraint held across one full execution
cycle: the leak, the `_service_env` fix that sets the storage dir, and the
`W04.P09.S29` follow-up that mirrors the qdrant binary under the isolated dir and
keeps the storage dir relocated.

## How

- **Good:** a fixture sets `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to
  `tmp_path / "qdrant-server" / "storage"`, calls `reset_config()`, then runs the
  identity write or lock acquire; teardown releases the lock and restores the
  env. The integration `_service_env` helper does exactly this, and additionally
  relocates the qdrant port off the shared default so a server-mode test daemon
  never binds the real machine's port.
- **Bad:** isolating only `VAULTSPEC_RAG_STATUS_DIR` (or only `config_override`)
  and then calling `write_qdrant_identity` / `acquire_machine_lock`; the
  machine-global paths still resolve to the real managed dir, leaking a sidecar
  or contending for the real machine lock.
