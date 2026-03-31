---
tags:
  - "#adr"
  - "#scheduler"
date: 2026-01-20
related:
  - "[[2026-01-20-scheduler-reference]]"
  - "[[2026-01-19-scheduling-algorithms-research]]"
  - "[[2026-01-20-scheduler-phase1-plan]]"
---

# ADR: Scheduler Algorithm — Earliest Deadline First | (**Status:** Accepted)

## Problem Statement

The Nexus scheduler assigns pipeline stages to worker threads. Multiple pipeline runs may be queued simultaneously, and stages within a single run have dependencies that constrain their ordering. The scheduling algorithm affects both average latency (time from stage ready to stage started) and fairness (no starvation of low-priority runs).

## Decision

Implement Earliest Deadline First (EDF) scheduling with soft deadlines derived from pipeline-level SLA targets.

## Considered Alternatives

### First-In-First-Out (FIFO)

- **Pro:** Interactive runs consistently meet their latency SLAs even when batch runs are queued.
- **Pro:** EDF degrades gracefully under overload — the scheduler correctly identifies which deadlines will be missed and reports them proactively.
