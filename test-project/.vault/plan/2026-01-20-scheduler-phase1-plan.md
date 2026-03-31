---
tags:
  - "#plan"
  - "#scheduler"
date: 2026-01-20
related:
  - "[[2026-01-20-scheduler-algorithm-choice]]"
  - "[[2026-01-20-scheduler-reference]]"
  - "[[2026-01-19-scheduling-algorithms-research]]"
---

# Scheduler Phase 1 Plan: Worker Pool and EDF Priority Queue

Implement the worker thread pool and the Earliest Deadline First priority queue so that ready pipeline stages are dispatched to available workers with correct priority ordering.

## Phase 1 Scope

1. **`WorkerPool`** — a fixed-size pool of threads, each pulling from the shared priority queue. Thread count is configurable at construction time (default: `2 × available_parallelism()`). Workers report completion via a `tokio::sync::mpsc` channel back to the executor.

2. **EDF Priority Queue** — a `BinaryHeap<ReadyStage>` ordered by absolute deadline. The `ReadyStage` struct carries `(pipeline_run_id, stage_id, deadline, work_fn)`. Insertion and pop are O(log n) on queue depth.

3. **Backpressure Signal** — when the ready queue depth exceeds `HIGH_WATERMARK` (default: `4 × worker_count`), the scheduler broadcasts a `Congested` signal via a `tokio::sync::watch` channel. Connector ingestion paths subscribe to this channel to pause record intake.

## Proposed Changes

### `src/scheduler/worker_pool.rs`

`WorkerPool::new(n_threads)` spawns `n_threads` worker threads. Each thread runs a tight loop: pop from queue (exponential backoff if empty, max 50ms sleep), execute the stage work function, send `StageComplete(stage_id, result)` on the completion channel.

### `src/scheduler/queue.rs`

`PriorityQueue` wraps `BinaryHeap` with a `Mutex` for thread-safe access. `push(stage)` inserts; `pop()` removes and returns the earliest-deadline ready stage. `depth()` returns current queue size for backpressure calculations.

### `src/scheduler/backpressure.rs`

`BackpressureMonitor` runs as a background task polling `queue.depth()` every 10ms. Sends `Congested` when depth > `HIGH_WATERMARK`; sends `Clear` when depth drops below `LOW_WATERMARK` (default: `2 × worker_count`).

## Acceptance Criteria

- With 4 workers, 100 ready stages of equal deadline are all executed within 2× of ideal parallel completion time.
- A stage with an earlier deadline preempts a later-deadline stage when a worker becomes available.
- Backpressure signal fires within 20ms of the queue exceeding `HIGH_WATERMARK`.
