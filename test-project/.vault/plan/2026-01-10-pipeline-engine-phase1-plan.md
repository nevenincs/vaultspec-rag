---
tags:
  - "#plan"
  - "#pipeline-engine"
date: 2026-01-10
related:
  - "[[2026-01-10-pipeline-execution-model]]"
  - "[[2026-01-10-pipeline-engine-reference]]"
  - "[[2026-01-09-dag-execution-research]]"
---

# Pipeline Engine Phase 1 Plan: Parser and Executor Foundation

Build the core DAG compiler and executor so that a well-formed pipeline definition produces correct stage outputs.

## Phase 1 Scope

Three components are required before any end-to-end pipeline execution is possible:

1. **Pipeline Definition Parser** — read YAML/TOML pipeline manifests and produce a validated `PipelineGraph` struct. Validation includes cycle detection, schema compatibility checks between connected stages, and parameter resolution.

2. **`NexusPipelineExecutor` Core** — implement the topological sort, dependency counter management, and worker submission loop described in the ADR ([[2026-01-10-pipeline-execution-model]]). The executor must handle stage failure by cancelling downstream stages and propagating the error to the caller.

3. **In-Memory Stage Result Store** — for Phase 1, intermediate stage outputs are held in memory. The durable checkpoint store (RocksDB) is deferred to Phase 2.

## Proposed Changes

### `src/parser/mod.rs`

Implement `PipelineGraph::from_manifest(path)`. The parser reads the stage list, resolves `inputs` references to upstream stage IDs, and builds an adjacency list. Cycle detection uses Kahn's algorithm. Error variants cover: unknown stage reference, schema mismatch, missing required parameter.

### `src/executor/mod.rs`

Implement `NexusPipelineExecutor`. The executor holds an `Arc<WorkerPool>` (created externally and injected). Stage dispatch is non-blocking: the executor pushes ready stages onto the work queue and waits asynchronously for completion notifications via a `tokio::sync::mpsc` channel.

### `src/executor/graph.rs`

`ExecutionGraph` tracks per-stage state: `Pending`, `Running`, `Succeeded(Output)`, `Failed(Error)`. Supports snapshot queries for monitoring.

## Acceptance Criteria

- A 10-stage linear pipeline runs to completion with correct output order.
- A 5-stage fan-out pipeline (one source, four parallel transforms, one sink) executes the four transforms concurrently.
- Introducing a cycle in the manifest returns a compile-time error with the cycle path in the message.
- Stage failure cancels all downstream stages; unrelated branches continue to completion.
