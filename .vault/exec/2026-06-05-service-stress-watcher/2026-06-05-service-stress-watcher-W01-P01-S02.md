---
tags:
  - '#exec'
  - '#service-stress-watcher'
date: '2026-06-06'
modified: '2026-06-30'
step_id: 'S02'
related:
  - '[[2026-06-05-service-stress-watcher-plan]]'
---

# Implement filesystem watcher file-creation integration test

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Add `test_watcher_detects_and_indexes_file` async test case.
- Establish active watcher loop using `watch_and_reindex` pointed at temporary directory.
- Verify file additions trigger debounced watcher execution and updates vector tables.

## Outcome

- Real-time file creation triggers automatic index refreshes in the watcher test case, validating system design.
