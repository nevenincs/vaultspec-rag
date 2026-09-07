---
tags:
  - '#exec'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:0f7a144437ea783f32f208a25af451e3d64f3de9b1cfb09ca67589c79b28bb82'
step_id: 'S07'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# Disable search-triggered mutation by default while retaining integrity reporting

## Scope

- `src/vaultspec_rag/_integrity_remediation.py`
- `src/vaultspec_rag/config/_settings.py`

## Changes

- `M` `src/vaultspec_rag/_integrity_remediation.py`
- `M` `src/vaultspec_rag/config/_settings.py`
- `verify:` `.venv\Scripts\python.exe -m pytest src/vaultspec_rag/tests/test_integrity_remediation.py::TestOperatorSwitch::test_disabling_auto_repair_keeps_detection_but_never_requests -q -p no:xdist` -> `pass`
