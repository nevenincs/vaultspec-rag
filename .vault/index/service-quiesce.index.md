---
generated: true
tags:
  - '#index'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-24-service-quiesce-P01-S01]]'
  - '[[2026-07-24-service-quiesce-P01-S02]]'
  - '[[2026-07-24-service-quiesce-P01-S03]]'
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-plan]]'
  - '[[2026-07-24-service-quiesce-research]]'
---

# `service-quiesce` feature index

Auto-generated index of all documents tagged with `#service-quiesce`.

## Documents

### adr

- `2026-07-24-service-quiesce-adr` - `service-quiesce` adr: `Cooperative zero-CPU GPU quiesce gate` | (**status:** `accepted`)

### exec

- `2026-07-24-service-quiesce-P01-S01` - Create the torch-free QuiesceGate primitive over a threading.Event with set equals running and clear equals paused, exposing wait, pause, resume and is_paused plus an absorbing-open latch so that once latched open wait returns immediately and pause and clear become no-ops, with positive unit tests that pause blocks a waiter and resume releases it
- `2026-07-24-service-quiesce-P01-S02` - Integrate the gate into RunControlToken as an optional injected reference where request_cancel and request_shutdown latch the gate open, checkpoint consults the gate first but only when protected depth is zero and re-checks absorbing signals after the gate releases, and a gateless token and NullRunControl stay no-op
- `2026-07-24-service-quiesce-P01-S03` - Add the both-direction guard tests covering worker blocks when quiesced with a bounded join timeout, worker resumes when released, shutdown wins over a concurrent re-pause, and a checkpoint inside a protected span never parks, each proven red-then-green in one sequence

### plan

- `2026-07-24-service-quiesce-plan` - `service-quiesce` plan

### research

- `2026-07-24-service-quiesce-research` - `service-quiesce` research: `Cooperative contention-aware GPU quiesce for the resident service`
