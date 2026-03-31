---
tags:
  - "#reference"
  - "#nexus-security-audit"
date: 2026-01-18
related:
  - "[[2026-01-10-pipeline-engine-reference]]"
  - "[[2026-01-12-connector-api-reference]]"
---

# Nexus Security Audit — 2026-01-18

## Scope

This security audit covers the Nexus pipeline engine, connector API, and scheduler components as implemented through the 2026-01-17 milestone. The audit focused on: input validation at connector ingestion boundaries, path traversal risks in the checkpoint store, and privilege escalation paths in the worker pool.

## Findings

### CRITICAL: None

No critical security vulnerabilities were identified.

### HIGH: Connector Record Payload Size Not Bounded

**Finding:** The `FileConnector` and gRPC `Fetch` implementation do not enforce a maximum `Record.payload` size. A malicious or misconfigured data source could produce records large enough to exhaust heap memory in the executor process.

**Recommendation:** Enforce `MAX_RECORD_PAYLOAD_BYTES = 16 MiB` at the connector boundary. Records exceeding this limit should be emitted with `error_payload: true` rather than silently truncated.

**Status:** Fix planned for next sprint.

### MEDIUM: Checkpoint Key Collision Under Run ID Reuse

**Finding:** The 24-byte checkpoint key `{run_id:16}{stage_id:8}` assumes run IDs are globally unique. The current run ID generation uses a monotonic counter scoped to a single process instance. If the process restarts with a reset counter, an old run's checkpoints could be overwritten by a new run with the same ID.

**Recommendation:** Use UUIDs (128-bit random) for run IDs rather than monotonic counters.

**Status:** Fix in progress.

### LOW: Worker Thread Stack Size Not Bounded

**Finding:** Worker threads are spawned with the platform default stack size (typically 8 MiB on Linux). Pipeline stages that use deep recursion or allocate large stack-local buffers may silently exceed this limit and trigger SIGSEGV.

**Recommendation:** Spawn worker threads with `Builder::new().stack_size(2 * 1024 * 1024)` (2 MiB) and profile stage stack usage during testing.

**Status:** Accepted as low risk for current workloads.

## Safety Review: `unsafe` Blocks

Two `unsafe` blocks exist in the codebase:

1. `src/storage/checkpoint.rs:214` — `transmute` of a raw RocksDB handle pointer. Safety invariant documented inline: the handle lifetime is tied to the `CheckpointStore` struct's lifetime via `PhantomData`. Reviewed and accepted.

2. `src/scheduler/worker_pool.rs:87` — `thread::Builder::spawn_unchecked`. Unnecessary; replaced with safe `thread::Builder::spawn` in the same review session.

## Summary

The Nexus codebase is in a good security posture for its current development stage. The HIGH-severity connector payload size issue should be addressed before accepting untrusted data sources. The run ID collision issue should be fixed before deploying to production environments with process restart scenarios.
