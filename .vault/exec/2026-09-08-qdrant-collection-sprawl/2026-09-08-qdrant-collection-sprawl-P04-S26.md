---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:da01476cada4a64731e2f761dd9a4a386e02d3eda24c8f652ba035da7b4757cb'
step_id: 'S26'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Point the qdrant storage-dir at a temp path in the storage-survey tests that reach the managed backend

## Scope

- `src/vaultspec_rag/tests/test_storage_survey.py`

## Changes

- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_survey.py` -> `pass`

## Notes

No file change: this file already scoped isolation correctly before this Step ran.
Every test that only classifies namespaces (`test_live_orphaned_unknown` and its
siblings) builds `ManifestEntry` values in memory and never touches
`storage-manifest.json`. The one class that does write it,
`TestSurveyTimeoutDoesNotUnwindTheCycle`, already carries its own
`@pytest.mark.usefixtures("isolated_status_dir")` rather than relying on a module-wide
fixture, which is exactly the narrow-scoping this Phase's sibling Step applies to
`test_storage_ops.py`. No test in this file constructs a real `QdrantClient`, calls
`storage_identity`, or takes the machine lock, so the storage-dir knob specifically
(as opposed to the status-dir knob `manifest_path()` actually resolves through) has
nothing to isolate here.

Verified against the operator's real backend rather than asserted: captured
`~/.vaultspec-rag/storage-manifest.json`'s root count (65), ran this file together with
`test_storage_ops.py`, `test_storage_ops_reclaim.py`, and `test_storage_safety.py`
(106 tests), and confirmed the count was still 65 afterward.

The 8 `vaultspec-livetest-*` roots present in the real manifest predate this Step:
their names carry a random 6-character `tempfile.mkdtemp` suffix that neither this
file's `is_temp_rooted` test (a fixed literal, `vaultspec-livetest-xyz`, asserted only
in memory) nor `test_storage_ops.py`'s `_temp_survey` helper (a fixed literal built
from a hardcoded test prefix, also never persisted) can produce, and the same literal
string does not appear anywhere else in the tree across any local worktree. Their
origin was not traced further, as doing so was outside this Step's scope.
