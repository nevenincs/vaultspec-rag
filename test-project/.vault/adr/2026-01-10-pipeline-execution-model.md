---
tags:
  - "#adr"
  - "#pipeline-engine"
date: 2026-01-10
related:
  - "[[2026-01-10-pipeline-engine-reference]]"
  - "[[2026-01-09-dag-execution-research]]"
  - "[[2026-01-10-pipeline-engine-phase1-plan]]"
---

# ADR: Pipeline Execution Model — DAG-Based Task Scheduling | (**Status:** Accepted)

## Problem Statement

Nexus requires a core execution model for processing multi-step data transformation workflows. Workflows can have arbitrary dependencies between stages, and stages may execute in parallel when their inputs are ready. A linear, sequential execution model would serialize all work and waste available parallelism.

## Decision

Adopt a directed acyclic graph (DAG) execution model where each node represents a processing stage and edges represent data dependencies between stages.

## Considered Alternatives

### Linear Pipeline

A strictly sequential execution model where each stage runs after the previous completes. Simple to implement but cannot express parallel execution. Rejected because real workloads frequently have fan-out patterns where multiple independent transformations can run simultaneously.

### Event-Driven Reactive Streams

Each stage emits events consumed by downstream stages. Suitable for streaming data but introduces backpressure complexity and makes deterministic replay difficult. Rejected for the initial version; may revisit for streaming use cases.

### DAG Execution (Selected)

Each workflow is compiled into a DAG. The executor performs a topological sort to determine execution order. Stages with no remaining dependencies are queued for concurrent execution by the worker pool. Results flow through typed channels from producer to consumer stages.

## Implementation Details

The `NexusPipelineExecutor` is the central orchestrator. It maintains a pending dependency count for each node and decrements it as upstream stages complete. Nodes reaching zero dependencies are immediately submitted to the scheduler. The executor tracks the execution state for each node in an `ExecutionGraph` struct, enabling both progress monitoring and failure recovery.

Stage isolation is enforced: each stage receives an immutable snapshot of its upstream outputs. Stages cannot mutate shared state.

## Consequences

- **Pro:** Natural expression of parallel workloads; stages execute as soon as their dependencies are satisfied.
- **Pro:** Deterministic replay — re-running a DAG from a checkpoint produces identical results given the same inputs.
- **Con:** Cycle detection must be performed at compile time; runtime cycle detection would add overhead.
- **Con:** Memory overhead from storing intermediate results across stage boundaries.
