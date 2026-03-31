---
tags:
  - "#research"
  - "#scheduler"
date: 2026-01-19
related:
  - "[[2026-01-20-scheduler-algorithm-choice]]"
  - "[[2026-01-20-scheduler-reference]]"
---

# Research: Task Scheduling Algorithms for Pipeline Workloads

## Summary

Reviewed scheduling algorithms (FIFO, SJF, EDF, Rate Monotonic, Work Stealing) to identify the best fit for Nexus pipeline stage dispatch.

## FIFO (First-In-First-Out)

The simplest scheduler: stages are dispatched in the order they become ready. O(1) enqueue and dequeue. Provides FIFO fairness but no priority differentiation. Under mixed workloads (interactive + batch), interactive runs must wait behind long-running batch jobs. Unsuitable for the Nexus use case where interactive and batch runs share the same worker pool.

## Shortest Job First (SJF)

Minimises average completion time by dispatching the smallest estimated job first. Provably optimal for average turnaround time assuming perfect estimates. In practice, stage execution time estimates are unreliable (data-dependent workloads). Prone to starvation of long-running stages. Not selected.

## Earliest Deadline First (EDF)

EDF is provably optimal among preemptive algorithms for meeting deadline constraints on a single processor. On multiprocessor systems, EDF remains optimal under the Liu-Layland model when total utilisation does not exceed processor count. Nexus uses non-preemptive EDF (a stage is not interrupted mid-execution) which is acceptable because stage granularity is designed to be minutes, not hours.

Implementation uses a `BinaryHeap<Reverse<deadline>>` for O(log n) insert and O(log n) pop. For the expected queue depths in Nexus (< 10,000 ready stages), this is negligible overhead.

## Rate Monotonic Scheduling (RMS)

Assigns priorities based on task period (shorter period = higher priority). Designed for periodic real-time tasks. Pipeline stages are not periodic — they execute once per run. RMS is not applicable.

## Work Stealing

Used by Tokio, Rayon, and the Java ForkJoinPool. Each worker thread has a local queue; when its queue is empty, it "steals" from the tail of another worker's queue. Excellent for recursive parallel workloads (divide-and-conquer). For Nexus, stage granularity is coarse enough that stealing overhead is not beneficial; a shared priority queue is simpler and sufficient.

## Conclusion

EDF with a shared `BinaryHeap` priority queue is the correct choice for Nexus. It provides deadline-aware priority ordering, is simple to implement and reason about, and has proven performance characteristics at the expected queue depths. Selected in the scheduler algorithm ADR.
