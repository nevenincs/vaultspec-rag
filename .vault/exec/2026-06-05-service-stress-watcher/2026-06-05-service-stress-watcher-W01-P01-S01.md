---
tags:
  - '#exec'
  - '#service-stress-watcher'
date: '2026-06-06'
modified: '2026-06-06'
step_id: 'S01'
related:
  - '[[2026-06-05-service-stress-watcher-plan]]'
---

# Implement concurrent database stress test under Server Mode

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Create test suite file containing local concurrency and lock checks.
- Add `test_local_mode_multi_process_raises_lock_error` asserting lock file conflicts.
- Add `test_local_mode_in_process_concurrency_serialized` validating that in-process threads are serialized via `_client_lock`.
- Add `test_server_mode_stress_concurrency` executing 50+ concurrent requests using a `ThreadPoolExecutor` to verify lack of lock contention in Qdrant Server Mode.

## Outcome

- Stress tests are available to verify lock contention in local mode and concurrency scalability in server mode.
