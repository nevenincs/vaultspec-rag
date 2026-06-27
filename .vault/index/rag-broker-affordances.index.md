---
generated: true
tags:
  - '#index'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
related:
  - '[[2026-06-27-rag-broker-affordances-P01-S01]]'
  - '[[2026-06-27-rag-broker-affordances-P01-S02]]'
  - '[[2026-06-27-rag-broker-affordances-P01-S03]]'
  - '[[2026-06-27-rag-broker-affordances-P01-S04]]'
  - '[[2026-06-27-rag-broker-affordances-P02-S05]]'
  - '[[2026-06-27-rag-broker-affordances-P02-S06]]'
  - '[[2026-06-27-rag-broker-affordances-P02-S07]]'
  - '[[2026-06-27-rag-broker-affordances-adr]]'
  - '[[2026-06-27-rag-broker-affordances-plan]]'
  - '[[2026-06-27-rag-broker-affordances-research]]'
---

# `rag-broker-affordances` feature index

Auto-generated index of all documents tagged with `#rag-broker-affordances`.

## Documents

### adr

- `2026-06-27-rag-broker-affordances-adr` - `rag-broker-affordances` adr: `idempotent JSON start and a machine-global discovery pointer` | (**status:** `accepted`)

### exec

- `2026-06-27-rag-broker-affordances-P01-S01` - Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller
- `2026-06-27-rag-broker-affordances-P01-S02` - Reorder service_start so the idempotent already-running check precedes the port and machine guards
- `2026-06-27-rag-broker-affordances-P01-S03` - Add the --json option and emit one envelope per outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway, start_timeout)
- `2026-06-27-rag-broker-affordances-P01-S04` - Unit-test the reorder and each --json outcome shape with an isolated temp status dir
- `2026-06-27-rag-broker-affordances-P02-S05` - Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module
- `2026-06-27-rag-broker-affordances-P02-S06` - Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown
- `2026-06-27-rag-broker-affordances-P02-S07` - Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir

### plan

- `2026-06-27-rag-broker-affordances-plan` - `rag-broker-affordances` plan

### research

- `2026-06-27-rag-broker-affordances-research` - `rag-broker-affordances` research: `broker-facing lifecycle affordances: idempotent start and machine-global discovery`
