---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S29'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Make the qdrant binary resolvable under the isolated test STATUS_DIR so the service-lifecycle integration tests exercise the live daemon attach and lock path instead of fast-failing on the binary guard in this env

## Scope

- `src/vaultspec_rag/tests/integration/_helpers.py`

## Description

- Make the managed qdrant binary resolvable under the isolated test status dir
  so server-mode lifecycle tests exercise the live daemon attach and lock path
  instead of fast-failing on the binary guard.
- Add `_resolve_host_provisioned_qdrant`, which resolves the host's real
  provisioned binary and manifest before any status-dir override.
- Add `_mirror_managed_qdrant_binary`, which copies that binary and its manifest
  verbatim into the isolated status dir's managed bin path.
- Wire both into the `_service_env` context manager: resolve the host binary
  first, then mirror it into the temp status dir after the env override.
- Relocate the qdrant port to an ephemeral port (with its grpc sibling free) so a
  server-mode test daemon never binds the shared machine default and never
  collides with the host's real qdrant or a sibling test.
- Add an integration test asserting the mirrored binary resolves from inside the
  isolated status dir and still hashes to the manifest's committed digest, and an
  end-to-end stop-by-port lifecycle test that depends on the live daemon path.

## Outcome

A server-mode test daemon now resolves a real provisioned binary from the
isolated status dir, and the pinned-digest verification is preserved: the
mirrored binary's SHA256 still matches the committed manifest digest, so the
supervisor's pre-execution re-hash continues to gate execution. The mirror is a
no-op when the host has no provisioned install, so air-gapped/CI hosts fall back
to local-only unchanged.

## Notes

The mirror copies the manifest verbatim rather than synthesizing one, so the
verification boundary is never weakened. The ephemeral qdrant-port picker
confirms both the http port and its grpc sibling bind before use.
