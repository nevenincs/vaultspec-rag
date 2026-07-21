---
generated: true
tags:
  - '#index'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-21-service-job-control-W01-P01-S01]]'
  - '[[2026-07-21-service-job-control-W01-P01-S02]]'
  - '[[2026-07-21-service-job-control-W01-P01-S03]]'
  - '[[2026-07-21-service-job-control-W01-P01-summary]]'
  - '[[2026-07-21-service-job-control-W01-P02-S04]]'
  - '[[2026-07-21-service-job-control-W01-P02-S05]]'
  - '[[2026-07-21-service-job-control-W01-P02-S06]]'
  - '[[2026-07-21-service-job-control-W01-P02-S07]]'
  - '[[2026-07-21-service-job-control-W01-P02-summary]]'
  - '[[2026-07-21-service-job-control-W01-P03-S08]]'
  - '[[2026-07-21-service-job-control-W01-P03-S09]]'
  - '[[2026-07-21-service-job-control-W01-P03-summary]]'
  - '[[2026-07-21-service-job-control-W01-P18-S38]]'
  - '[[2026-07-21-service-job-control-W01-P18-S39]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-07-21-service-job-control-plan]]'
  - '[[2026-07-21-service-job-control-reference]]'
  - '[[2026-07-21-service-job-control-research]]'
  - '[[2026-07-21-service-job-control-s02-config-audit]]'
  - '[[2026-07-21-service-job-control-s03-tests-audit]]'
  - '[[2026-07-21-service-job-control-s39-persistence-audit]]'
  - '[[2026-07-21-service-job-control-wave-1-audit]]'
---

# `service-job-control` feature index

Auto-generated index of all documents tagged with `#service-job-control`.

## Documents

### adr

- `2026-07-21-service-job-control-adr` - `service-job-control` adr: `desired-state control for indexing jobs` | (**status:** `accepted`)

### audit

- `2026-07-21-service-job-control-s02-config-audit` - `service-job-control` audit: `s02 config`
- `2026-07-21-service-job-control-s03-tests-audit` - `service-job-control` audit: `s03 tests`
- `2026-07-21-service-job-control-s39-persistence-audit` - `service-job-control` audit: `S39 persistence boundary`
- `2026-07-21-service-job-control-wave-1-audit` - `service-job-control` audit: `Wave 1 state authority`

### exec

- `2026-07-21-service-job-control-W01-P01-S01` - Define the thread-safe run-control token, checkpoint signals, protected spans, and no-control implementation using vaultspec-high-executor
- `2026-07-21-service-job-control-W01-P01-S02` - Add bounded nonterminal admission and cooperative shutdown timing settings using vaultspec-standard-executor
- `2026-07-21-service-job-control-W01-P01-S03` - Verify control primitives and configuration through imported production behavior using vaultspec-standard-executor
- `2026-07-21-service-job-control-W01-P01-summary` - `service-job-control` `W01.P01` summary
- `2026-07-21-service-job-control-W01-P02-S04` - Define immutable job specifications, canonical states, capabilities, revisions, attempt lineage, and structured outcomes using vaultspec-high-executor
- `2026-07-21-service-job-control-W01-P02-S05` - Implement exact-ID active and runtime ownership, bounded terminal history, admission, active-work deduplication, and idempotency keys using vaultspec-high-executor
- `2026-07-21-service-job-control-W01-P02-S06` - Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor
- `2026-07-21-service-job-control-W01-P02-S07` - Implement atomic durable-before-dispatch persistence and queued, paused, and interrupted restart recovery using vaultspec-high-executor
- `2026-07-21-service-job-control-W01-P02-summary` - `service-job-control` `W01.P02` summary
- `2026-07-21-service-job-control-W01-P03-S08` - Verify the transition matrix, idempotency, stale revisions, admission, deduplication, retry, deletion, and terminal immutability using vaultspec-standard-executor
- `2026-07-21-service-job-control-W01-P03-S09` - Verify real-filesystem persistence, exact task ownership, atomic replacement, paused restoration, and interrupted recovery using vaultspec-standard-executor
- `2026-07-21-service-job-control-W01-P03-summary` - `service-job-control` `W01.P03` summary
- `2026-07-21-service-job-control-W01-P18-S38` - Extract canonical enums, immutable resources, outcomes, and serialization into a focused model module while preserving public imports using vaultspec-standard-executor
- `2026-07-21-service-job-control-W01-P18-S39` - Extract the versioned state codec and atomic filesystem store into a focused persistence module using vaultspec-standard-executor

### plan

- `2026-07-21-service-job-control-plan` - `service-job-control` plan

### reference

- `2026-07-21-service-job-control-reference` - `service-job-control` reference: `current indexing job runtime and control seams`

### research

- `2026-07-21-service-job-control-research` - `service-job-control` research: `CRUD and lifecycle control for indexing jobs`
