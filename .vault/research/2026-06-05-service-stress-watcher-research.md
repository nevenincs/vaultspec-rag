---
title: Service Stress and Watcher Verification Research
source: RAG watcher and store codebase
relevance: 10
tags:
  - '#research'
  - '#service-stress-watcher'
date: '2026-06-05'
modified: '2026-06-05'
related: []
---

# `service-stress-watcher` research: `Service Stress and Watcher Verification`

This research investigates the concurrency, write contention, and filesystem watcher behavior of the vaultspec-rag package. It analyzes the causes of database lock contention under simultaneous read/write loads and evaluates the functionality and test coverage of the automatic filesystem watcher.

## Findings

### 1. Concurrency and Write Contention in Local vs. Server Mode

- **Local Mode Locks**: When running in local mode (`qdrant_url` is not set), Qdrant utilizes an in-process SQLite-backed store. SQLite enforces process-exclusive write locks, causing any parallel process attempting a search, check, or concurrent index to raise `VaultStoreLockedError`.
- **Server Mode Concurrency**: In Qdrant Server Mode (`qdrant_url` is configured), transactions are managed by Qdrant's Rust-native backend. Multiple Python client processes can execute concurrent search queries and index updates simultaneously without file lock contentions.

### 2. Filesystem Watcher Verification and Cooldown Gaps

- **The awatch Loop**: The automatic re-indexing service monitors `.vault/` and code files using the `watchfiles` library. It groups detected paths in `pending_vault` or `pending_code`, debounces events, and schedules `incremental_index` runs inside a background thread pool.
- **Cooldown Mechanism**: To prevent write thrashing, a cooldown window (default 30s) suppresses successive re-index triggers. If files are modified while a cooldown is active, the paths remain in `pending_vault`/`pending_code` and are processed on the next available interval.
- **Test Coverage Gap**: Existing tests only check command exit codes when the server is offline. There is no active test validating that writing a physical file to disk wakes the watcher, runs the linter/indexer, and propagates the new content into searchable vector space.

### 3. Stress Testing Requirements

To ensure robustness against concurrent reads and writes, we must introduce a stress-testing suite that:

- Spawns multiple concurrent search tasks while simultaneously triggering codebase/vault re-indexes.
- Asserts that in server mode, these operations run in parallel without raising database lock errors.
- Verifies that the filesystem watcher correctly detects new source files on disk, runs the incremental indexer, and makes the new code blocks searchable.
