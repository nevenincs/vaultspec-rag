---
feature: nexus-pipeline-audit
date: 2026-01-24
related:
  - "[[2026-01-18-nexus-security-audit]]"
  - "[[2026-01-10-pipeline-engine-reference]]"
---

# Nexus Pipeline Engine Audit — 2026-01-24

## Scope

Targeted audit of the `NexusPipelineExecutor` dispatch loop and `ExecutionGraph` state transitions. Focuses on correctness of the dependency counter decrement and the stage cancellation path.

## Findings

### Dependency Counter Correctness

Reviewed `ExecutionGraph::advance(stage_id, output)`. The method decrements the `pending_deps` counter for each downstream stage by iterating over the adjacency list. No edge case was found where the counter could decrement below zero or fail to reach zero for valid DAGs.

One concern: if `advance` is called more than once for the same stage (e.g., due to a retry), the dependency counters of downstream stages would be decremented a second time, potentially triggering premature dispatch. Recommendation: guard `advance` with a check that the stage is currently in `Running` state before accepting the output.

**Status:** Medium risk. Fix recommended before production deployment.

### Cancellation Path

`ExecutionGraph::cancel_downstream` uses a recursive traversal. For deep pipeline graphs (>100 stages deep), this could overflow the call stack. Python's default recursion limit is 1000; a 100-stage linear pipeline cancelling from stage 1 would require 99 recursive calls, safely within limits. For graphs exceeding 500 nodes, an iterative BFS cancellation is recommended.

**Status:** Low risk for current workload sizes.

### Stage State Machine

The `StageState` enum transitions are: `Pending → Running → Succeeded | Failed | Cancelled`. No invalid transitions were observed in the current implementation. The executor correctly prevents submitting a stage that is already in `Running` state.

## Summary

The pipeline engine is sound for the current workload profile. Two non-critical findings are recommended for remediation before the system handles untrusted pipeline manifests or very large graph topologies.
