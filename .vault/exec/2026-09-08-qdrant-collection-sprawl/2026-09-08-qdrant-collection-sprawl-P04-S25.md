---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:3a7fdbbadd622fd8b8adc935321931e7a159e98cf973c93e46bc5a8f1ae5e94d'
step_id: 'S25'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Point the qdrant storage-dir at a temp path in the storage-ops tests that reach the managed backend

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py src/vaultspec_rag/tests/test_storage_survey.py` -> `pass`

## Notes

No test here reaches a live qdrant client or the identity sidecar / machine lock:
every client in this file is a fake, and `manifest_path()` resolves only through
`VAULTSPEC_RAG_STATUS_DIR`. What was real was cross-test manifest pollution: a
module-wide autouse fixture isolated every test's status dir regardless of whether
that test ever wrote to the manifest. Replaced it with
`@pytest.mark.usefixtures("isolated_status_dir")` on only the six classes that call
`record_root`/`update_orphan_stamps`/`update_activity_stamps` (`TestOrphanStamps`,
`TestLastIndexedStamping`, `TestPreDropRecount`, `TestLivenessGate`,
`TestActivityClock`, `TestEphemeralTierNeedsObservedStability`), matching the existing
narrow-scoping idiom already established in `TestEphemeralWindowKeepsEveryDestructionGate`
(`test_storage_safety.py`). Proved this is load-bearing rather than decorative: with the
decorator removed from two of the six classes, a full-file run left 4 stale entries in
the shared manifest and `test_fresh_stamp_overwrites_and_persists` failed reading the
wrong one via `next(iter(load_manifest().values()))`; restored, all 55 tests pass.

Verified against the operator's real backend rather than asserted: captured
`~/.vaultspec-rag/storage-manifest.json`'s root count (65) before touching anything, ran
this file's full suite plus the three sibling files that import its helpers (106 tests),
and confirmed the count was still 65 afterward - the same result the untouched file
already produced, since nothing here was ever unisolated at the session level.

`test_storage_ops_reclaim.py` uses `_orphaned_namespace` (which calls `record_root`)
with no isolation fixture of its own; that file is outside this Step's scope
(`src/vaultspec_rag/tests/test_storage_ops.py` only) and was left untouched, but the
gap is worth a maintainer's attention.
