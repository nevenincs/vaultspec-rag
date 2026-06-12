---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
step_id: 'S03'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Implement host-pinned download, SHA256 verify before extraction, extraction, manifest, idempotent unchanged, and dry-run reporting in the sync vocabulary, with unit tests including the uv.lock minor-pin guard

## Scope

- `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `src/vaultspec_rag/tests/test_qdrant_runtime.py`

## Description

- Add `qdrant_runtime/_provision.py`: HTTPS download host-pinned to github.com /
  objects.githubusercontent.com with redirect rejection outside the set, SHA256
  verification strictly before extraction (`extract_verified_archive`), single-member
  archive extraction (zip and tar.gz shapes), executable bit, atomic manifest write,
  idempotent `unchanged` short-circuit with zero network, stale-install protection
  requiring `--upgrade`, operator-binary registration, dry-run that writes nothing,
  bounded `provisioned_versions()`, and `clean_provisioned()`.
- Add `tests/test_qdrant_runtime.py`: 27 unit tests covering the above plus the
  uv.lock minor-pin guard (server 1.18 minor == locked qdrant-client 1.18 minor).

## Outcome

27/27 unit tests pass with zero network I/O; checksum mismatch deletes the partial and
extracts nothing; dry-run leaves the managed dir absent; pre-seeded verified install
reports `unchanged` without rewriting the binary.

## Notes

Idempotency is proven by pre-seeding the versioned dir with a verified manifest because
downloads are host-pinned to upstream - a file:// fixture cannot stand in for the network
leg by design.
