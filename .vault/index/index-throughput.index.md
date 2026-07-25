---
generated: true
tags:
  - '#index'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-24-index-throughput-P01-S01]]'
  - '[[2026-07-24-index-throughput-P01-S02]]'
  - '[[2026-07-24-index-throughput-P01-S14]]'
  - '[[2026-07-24-index-throughput-P02-S03]]'
  - '[[2026-07-24-index-throughput-P02-S04]]'
  - '[[2026-07-24-index-throughput-P02-S15]]'
  - '[[2026-07-24-index-throughput-P03-S06]]'
  - '[[2026-07-24-index-throughput-P03-S07]]'
  - '[[2026-07-24-index-throughput-P03-S08]]'
  - '[[2026-07-24-index-throughput-P03-S10]]'
  - '[[2026-07-24-index-throughput-P03-S16]]'
  - '[[2026-07-24-index-throughput-P03-S17]]'
  - '[[2026-07-24-index-throughput-P04-S13]]'
  - '[[2026-07-24-index-throughput-P04-S18]]'
  - '[[2026-07-24-index-throughput-adr]]'
  - '[[2026-07-24-index-throughput-plan]]'
  - '[[2026-07-24-index-throughput-research]]'
---

# `index-throughput` feature index

Auto-generated index of all documents tagged with `#index-throughput`.

## Documents

### adr

- `2026-07-24-index-throughput-adr` - `index-throughput` adr: `bound job admission and align pipeline overlap` | (**status:** `accepted`)

### exec

- `2026-07-24-index-throughput-P01-S01` - implement the machine-wide encode-job admission gate in the job dispatch layer with honest queued state stamped on job records
- `2026-07-24-index-throughput-P01-S02` - add admission-gate tests including the mutation proof: bypass the gate, the concurrency assertion goes red on the intended assertion, restore green, both directions recorded
- `2026-07-24-index-throughput-P01-S14` - stamp admission-acquired time on job records and accumulate per-job GPU-lock wait via a timed-acquire helper, publishing both through the existing jobs envelope so queued-shown-as-running is fixed
- `2026-07-24-index-throughput-P02-S03` - pass explicit non-blocking wait semantics on rebuild-path upserts and add the completion barrier before stale-purge and metadata publish
- `2026-07-24-index-throughput-P02-S04` - add ingest-barrier tests including the mutation proof: remove the barrier, the terminal-state-precedes-applied-points assertion goes red, restore green, both directions recorded
- `2026-07-24-index-throughput-P02-S15` - switch the server-mode store client to gRPC transport and record the measured per-batch upsert delta
- `2026-07-24-index-throughput-P03-S10` - add overlap tests including mutation proofs that the single-consumer contract binds: a second consumer or lock-held-across-non-forward mutation goes red on the intended assertion, restore green, recorded
- `2026-07-24-index-throughput-P03-S16` - apply the existing flush-cadence throttle to the vault slice path, which currently empties the CUDA cache every slice
- `2026-07-24-index-throughput-P03-S17` - throttle the document per-file loop's cache release, which currently syncs the device every slice by defaulting release-cache on
- `2026-07-24-index-throughput-P04-S18` - cap requires-python below 3.14 so the published metadata matches the runtime interpreter guard that already rejects 3.14, and add a .python-version pin so fresh worktree venvs resolve a supported interpreter
- `2026-07-24-index-throughput-P03-S06` - move vault document parsing into the spawn-safe CPU worker pool keeping every worker torch-free
- `2026-07-24-index-throughput-P03-S07` - adopt the bounded-queue producer/consumer pattern for the vault encode path with sentinel shutdown and time-bounded joins
- `2026-07-24-index-throughput-P03-S08` - adopt the bounded-queue producer/consumer pattern for the document encode path with sentinel shutdown and time-bounded joins
- `2026-07-24-index-throughput-P04-S13` - commit the throughput work with a why-focused message and push to origin main

### plan

- `2026-07-24-index-throughput-plan` - `index-throughput` plan

### research

- `2026-07-24-index-throughput-research` - `index-throughput` research: `where reindex wall-clock goes`
