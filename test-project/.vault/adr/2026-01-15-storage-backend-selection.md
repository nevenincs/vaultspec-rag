---
tags:
  - "#adr"
  - "#pipeline-engine"
date: 2026-01-15
related:
  - "[[2026-01-10-pipeline-engine-reference]]"
  - "[[2026-01-09-dag-execution-research]]"
  - "[[2026-01-16-storage-integration-complete]]"
---

# ADR: Storage Backend Selection — RocksDB for Stage Checkpoints | (**Status:** Accepted)

## Problem Statement

Long-running pipeline executions must be recoverable after process restarts. Stage outputs need to be checkpointed to durable storage so that execution can resume from the last successful stage rather than restarting from the beginning. The checkpoint store must handle high write throughput and support range scans for retrieving all checkpoints associated with a given pipeline run.

## Decision

Use RocksDB (via the `rocksdb` crate) as the embedded checkpoint storage backend.

## Considered Alternatives

### SQLite

- **Pro:** Atomic batch writes ensure that a checkpoint either fully commits or is absent; no partial state visible to the executor.
- **Con:** RocksDB compaction activity can cause write stalls under heavy sustained load; tuning compaction threads is required for production deployments.
- **Con:** Embedded; cannot be shared across multiple Nexus worker processes without a proxy layer.
