---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S10'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Integration test: provision the real binary, run a server-mode vault and code index plus hybrid search round trip on an ephemeral port with temp storage, assert per-root prefixes and clean child reaping

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

- Add `tests/integration/test_qdrant_server_mode.py` (real binary, real GPU, no mocks):
  module fixture provisions the real pinned binary (idempotent across runs) and
  supervises one server on an ephemeral loopback port with temp storage.
- Round-trip test: store opens with `_server_mode` and null point locks, vault + code
  full index, hybrid vault and code searches return hits through the Rust engine.
- Namespacing test: two roots produce differently prefixed collections visible on the
  same server.
- Supervision tests: `stop()` reaps the child (PID dead, no orphan); a killed child is
  recovered by the single bounded `restart()` and serves the pinned version again.

## Outcome

Suite green on the RTX 4080 against qdrant 1.18.2. Two field fixes fell out of running
against the real artifact: GitHub now redirects release downloads to
`release-assets.githubusercontent.com` (host added to the pinned allow-set after the
pin correctly rejected it), and the `.partial` staging suffix defeated zip/tar format
sniffing in extraction (fixed plus `tarfile.TarError`/`BadZipFile` now report `failed`
instead of crashing).

## Notes

Validation runs surfaced an environment hazard, not a code defect: the shared C: drive
hit 0 bytes free mid-run (qdrant mmap preallocation then fails with os error 112 and
misleading os error 3 variants) and the shared GPU was intermittently saturated by
sibling sessions, which can push model-load past the 300s per-test timeout. Re-runs on
a free GPU pass.
