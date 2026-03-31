---
tags:
  - "#reference"
  - "#scheduler"
date: 2026-01-20
related:
  - "[[2026-01-20-scheduler-algorithm-choice]]"
  - "[[2026-01-20-scheduler-phase1-plan]]"
---

# Scheduler Reference

## Overview

The Nexus scheduler manages a worker thread pool and dispatches ready pipeline stages using Earliest Deadline First (EDF) ordering.

## `WorkerPool`

```rust
pub struct WorkerPool {
    queue: Arc<Mutex<PriorityQueue>>,
    completion_tx: mpsc::Sender<StageComplete>,
    handles: Vec<JoinHandle<()>>,
}

impl WorkerPool {
    pub fn new(n_threads: usize) -> (Self, mpsc::Receiver<StageComplete>);
    pub fn submit(&self, stage: ReadyStage);
    pub fn depth(&self) -> usize;
    pub fn shutdown(self);
}
```

`new(n_threads)` spawns `n_threads` worker threads. Returns both the pool and the `StageComplete` receiver. The `NexusPipelineExecutor` holds the receiver and polls it for completed stages.

## `PriorityQueue`

The priority queue is a `BinaryHeap<ReadyStage>` ordered by `Reverse<deadline>` (earliest deadline = highest priority).

```rust
pub struct ReadyStage {
    pub pipeline_run_id: u128,
    pub stage_id: u64,
    pub deadline: Instant,
    pub work_fn: Box<dyn FnOnce() -> StageOutput + Send>,
}
```

`PriorityQueue::push(stage)` inserts in O(log n). `PriorityQueue::pop()` removes the highest-priority (earliest deadline) stage in O(log n).

## `BackpressureMonitor`

```rust
pub struct BackpressureMonitor {
    high_watermark: usize,
    low_watermark: usize,
    state_tx: watch::Sender<BackpressureState>,
}

pub enum BackpressureState {
    Clear,
    Congested,
}
```

`BackpressureMonitor` runs as a background thread. It polls `pool.depth()` every 10ms. Transitions:

- `Clear → Congested` when `depth > high_watermark`
- `Congested → Clear` when `depth < low_watermark`

Default watermarks: `high = 4 × worker_count`, `low = 2 × worker_count`.

## Worker Thread Behavior

Each worker thread runs a loop:

1. Lock the `PriorityQueue` and call `pop()`.
2. If the queue is empty: release the lock, back off (1ms, 2ms, 4ms, … capped at 50ms), retry.
3. If a stage is found: execute `work_fn()`, send `StageComplete(stage_id, output)` on the completion channel.

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `worker_threads` | `2 × CPU count` | Number of worker threads |
| `high_watermark` | `4 × worker_threads` | Queue depth triggering `Congested` |
| `low_watermark` | `2 × worker_threads` | Queue depth clearing `Congested` |
| `backoff_max_ms` | `50` | Maximum worker poll backoff in ms |
