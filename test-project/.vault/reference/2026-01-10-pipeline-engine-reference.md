---
tags:
  - "#reference"
  - "#pipeline-engine"
date: 2026-01-10
related:
  - "[[2026-01-10-pipeline-execution-model]]"
  - "[[2026-01-10-pipeline-engine-phase1-plan]]"
---

# Pipeline Engine Reference

## Overview

The pipeline engine executes directed acyclic graph (DAG) workflows. The central class is `NexusPipelineExecutor`, which coordinates stage scheduling, dependency tracking, and result collection.

## `NexusPipelineExecutor`

The `NexusPipelineExecutor` is initialized with a compiled `ExecutionGraph` and an `Arc<WorkerPool>`. It drives the execution loop until all stages complete or a failure is propagated.

```rust
pub struct NexusPipelineExecutor {
    graph: ExecutionGraph,
    pool: Arc<WorkerPool>,
    checkpoint: Option<Arc<CheckpointStore>>,
}

impl NexusPipelineExecutor {
    pub fn new(graph: ExecutionGraph, pool: Arc<WorkerPool>) -> Self { ... }
    pub fn with_checkpoint(mut self, store: Arc<CheckpointStore>) -> Self { ... }
    pub async fn run(self) -> Result<PipelineOutput, ExecutionError> { ... }
}
```

### Execution Loop

`NexusPipelineExecutor::run()` performs the following steps:

1. Query the `ExecutionGraph` for all stages with zero pending dependencies.
2. Submit each ready stage to the `WorkerPool` via `pool.submit(stage_fn)`.
3. Await completion events on the worker completion channel.
4. For each completed stage: record the output, decrement dependency counts for downstream stages, and submit newly ready stages.
5. Repeat until `ExecutionGraph::all_complete()` or an error is returned.

## `ExecutionGraph`

`ExecutionGraph` maintains the full pipeline topology and per-stage execution state.

```rust
pub enum StageState {
    Pending { remaining_deps: usize },
    Running,
    Succeeded(StageOutput),
    Failed(ExecutionError),
    Cancelled,
}
```

`ExecutionGraph::ready_stages()` returns all stages in `Pending { remaining_deps: 0 }` state. `ExecutionGraph::advance(stage_id, output)` transitions a stage to `Succeeded` and decrements dependency counts.

## `NexusPipelineExecutor` Error Handling

When a stage transitions to `Failed`, `NexusPipelineExecutor` cancels all transitive downstream stages by traversing the dependency edges and marking them `Cancelled`. Stages already in `Running` state are allowed to complete (their results are discarded). The executor then returns `Err(ExecutionError::StageFailed { stage_id, cause })`.

## `PipelineGraph::from_manifest`

Compiles a YAML or TOML manifest file into an `ExecutionGraph`. Performs:

- Stage ID uniqueness check
- Cycle detection using Kahn's algorithm
- Schema compatibility validation between connected stages
- Parameter resolution from environment and manifest overrides

Returns `Err(ParseError)` on any validation failure, with the error message identifying the offending stage or connection.

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `worker_threads` | `2 × CPU count` | Worker pool size |
| `checkpoint_enabled` | `false` | Enable RocksDB checkpoint persistence |
| `stage_timeout_secs` | `300` | Per-stage execution timeout |
| `max_concurrent_stages` | `unlimited` | Cap on simultaneously running stages |
