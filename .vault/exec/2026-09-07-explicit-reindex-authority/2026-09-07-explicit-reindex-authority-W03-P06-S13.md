---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:08d09a36de73b23b4847ee583a68a0c0fb14ead936eb7ae665374cc86c3fe00b'
step_id: 'S13'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Add mutation-proven unit guards for automatic full-work refusal

## Scope

- `src/vaultspec_rag/tests`

## Changes

- `M` `src/vaultspec_rag/tests/test_document_index_escalation.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `M` `src/vaultspec_rag/tests/test_integrity_remediation.py`
- `M` `src/vaultspec_rag/tests/test_watcher_retry.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_integrity_remediation.py src/vaultspec_rag/tests/test_watcher_retry.py::test_full_reindex_required_is_terminal_and_clears_pending_intent src/vaultspec_rag/tests/test_index_run_ledger.py::test_backend_identity_is_part_of_manifest_compatibility -q -p no:xdist` -> `pass`
