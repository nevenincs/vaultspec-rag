---
title: Robust Stress Testing and Filesystem Watcher Verification ADR
source: 2026-06-05-service-stress-watcher-research
relevance: 10
tags:
  - '#adr'
  - '#service-stress-watcher'
date: '2026-06-05'
modified: '2026-06-05'
related:
  - '[[2026-06-05-service-stress-watcher-research]]'
---

# `service-stress-watcher` adr: `Robust Stress Testing and Filesystem Watcher Verification` | (**status:** `accepted`)

## Problem Statement

To assure production readiness of the new Qdrant Server Mode and the automatic background watcher, we must verify that the codebase is resilient under simultaneous concurrent read/write transactions (mimicking parallel agent searches and background watcher re-indexing). We must also verify that the filesystem watcher is fully functional on real file modifications, filling the current integration test gaps.

## Considerations

- **Real Concurrency**: The test suite must trigger multiple concurrent read and write operations on the vector store.
- **Real File Events**: The test suite must write to actual files on the disk, let the watcher detect them, debounce, trigger incremental indexing, and verify that the added content becomes searchable.
- **Backward Compatibility**: The tests must confirm that local-file mode raises the expected lock errors, whereas server mode routes queries concurrently without contention.

## Constraints

- **Watchfiles Async Loop**: Testing `watchfiles` requires running an async loop and scheduling file writes in a separate thread/task to avoid blocking the test runner.
- **Port Availability**: Network integration tests must run on an isolated port to avoid interfering with any running service daemon in the workspace.

## Implementation

1. **Stress Test Suite**: Create `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py` containing:
   - A concurrent stress test querying the store with 20+ parallel search tasks while performing incremental indexing.
   - An integration test verifying the filesystem watcher by creating a temporary file in a watched directory, yielding execution control, and asserting that the new document is indexed automatically and searchable.
1. **Execution Gating**: Stress tests require a running Qdrant instance. If `VAULTSPEC_RAG_QDRANT_URL` is not set or the server is offline, the test suite must skip network-only stress testing cleanly while still executing local-mode lock assertions.

## Rationale

Grounded in findings from `2026-06-05-service-stress-watcher-research`, we need explicit validation of the filesystem watcher loop and concurrency handling. Designing a dedicated stress-testing suite ensures the system does not regress when deployed to production under agent-heavy parallel usage.

## Consequences

- **Gains**:
  - High-confidence verification of watcher re-indexing and debounce logic.
  - Prevention of concurrency bottlenecks and SQLite lock contention.
- **Pitfalls**:
  - Testing filesystem watchers introduces brief async delays (sleep/debounce duration) into the test suite.

## Codification candidates

- **Rule slug:** `watcher-integration-testing`.
  **Rule:** Any auto-indexing or filesystem-watcher feature must carry an integration test that performs physical disk writes and verifies subsequent search retrieval.
