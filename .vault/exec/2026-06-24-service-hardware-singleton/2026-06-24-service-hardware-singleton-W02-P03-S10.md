---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S10'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Unit-test identity write and validation

## Scope

- `src/vaultspec_rag/tests/test_qdrant_identity.py`

## Description

- Authored `test_qdrant_identity.py` (no mocks, no GPU): a `temp_storage` fixture points the
  storage dir at a temp path via the genuine `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` env knob with
  finally-cleanup + `reset_config`; tests the write/read round-trip and missing-sidecar case,
  and exercises `verify_attachable` across all gates.

## Outcome

7 tests pass in ~0.15s, no GPU. The identity sidecar and the attach gate are verified.
`ruff` and `ty` pass.

## Notes

`config_override` does not reach `qdrant_storage_dir` (a RAG-default key, not a base-config
attribute), so the test drives the real env knob with finally-restore - the same way the
service is configured, no monkeypatch, no mock. No blockers.
