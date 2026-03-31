---
tags:
  - "#research"
  - "#pipeline-engine"
date: 2026-01-09
related:
  - "[[2026-01-10-pipeline-execution-model]]"
  - "[[2026-01-10-pipeline-engine-reference]]"
---

# Research: DAG Execution Models for Data Processing Pipelines

## Summary

Surveyed execution models used by Apache Airflow, Prefect, Dagster, and academic stream processing systems to inform the Nexus pipeline engine design.

## Apache Airflow

Airflow represents workflows as DAGs of `Operator` instances. The scheduler performs a topological sort and submits tasks to an executor backend (LocalExecutor, CeleryExecutor, KubernetesExecutor). The DAG parser runs on a schedule rather than on-demand, introducing up to 30 seconds of latency between workflow submission and first task execution.

**Relevant to Nexus:** The distinction between the DAG definition (static Python code) and the run-time `DagRun` instance is important. Nexus adopts a similar compile-time vs. run-time separation: `PipelineGraph` (static) vs. `ExecutionGraph` (runtime).

## Prefect

Prefect 2.x uses a `TaskRunner` abstraction that can execute tasks locally, on Dask workers, or on Ray. The `ConcurrentTaskRunner` uses Python `asyncio` for light-weight concurrency. The dependency graph is built implicitly by tracking `Future` objects returned by task calls.

**Relevant to Nexus:** Implicit graph construction via future tracking is ergonomic but makes static analysis harder. Nexus uses explicit manifest files for better toolability.

## Dagster

Dagster's `asset` and `op` model separates data assets (persistent outputs) from computation. The `JobDefinition` compiles to an execution plan that the Dagster engine schedules. Strong type system for asset schemas with static validation.

**Relevant to Nexus:** Dagster's schema validation approach at asset boundaries informed the `NexusPipelineExecutor` schema compatibility check between connected stages.

## Academic Baseline: Tomasulo Algorithm

The Tomasulo out-of-order execution algorithm (originally for CPU instruction scheduling) is conceptually analogous to DAG-based pipeline scheduling. Dependency counters (reservation stations in Tomasulo) track when an operation's inputs are ready. This is the model adopted by the `NexusPipelineExecutor` dependency counter decrement loop.

## Conclusion

A compile-time DAG with explicit schema validation (Dagster-inspired) combined with a runtime dependency counter loop (Tomasulo-inspired) provides the best combination of static safety guarantees and low-latency execution. This combination is adopted in the pipeline execution model ADR.
