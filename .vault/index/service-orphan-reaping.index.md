---
generated: true
tags:
  - '#index'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
related:
  - '[[2026-07-23-service-orphan-reaping-P01-S02]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S01]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S03]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S04]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S05]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S06]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S07]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S08]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S09]]'
  - '[[2026-07-23-service-orphan-reaping-P04-S10]]'
  - '[[2026-07-23-service-orphan-reaping-adr]]'
  - '[[2026-07-23-service-orphan-reaping-plan]]'
  - '[[2026-07-23-service-orphan-reaping-research]]'
  - '[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]'
---

# `service-orphan-reaping` feature index

Auto-generated index of all documents tagged with `#service-orphan-reaping`.

## Documents

### adr

- `2026-07-23-service-orphan-reaping-adr` - `service-orphan-reaping` adr: `guaranteed daemon self-exit on a failed claim, plus a bounded signature-scoped reap` | (**status:** `accepted`)

### exec

- `2026-07-23-service-orphan-reaping-P02-S01` - Move the machine-singleton claim inside the lifespan startup try-guard so its failure routes through \_exit_standalone_daemon
- `2026-07-23-service-orphan-reaping-P02-S03` - Make the release-on-failure teardown tolerate a claim that produced no lease
- `2026-07-23-service-orphan-reaping-P02-S04` - Add a top-level entrypoint os.\_exit backstop on any startup exception escaping uvicorn.run
- `2026-07-23-service-orphan-reaping-P03-S06` - Add the daemon-signature enumeration and the lock-and-pointer-anchored reap predicate
- `2026-07-23-service-orphan-reaping-P03-S07` - Wire the opt-in server stop --orphans flag with its structured reaped-count success and refusal-fault envelope
- `2026-07-23-service-orphan-reaping-P03-S08` - Add guard tests that the reap never targets the singleton, a foreign process, or an isolated-config instance
- `2026-07-23-service-orphan-reaping-P01-S02` - Reproduce a race-losing daemon in an isolated sandbox and capture the launcher-daemon process tree, persisting the pair-origin confirmation
- `2026-07-23-service-orphan-reaping-P02-S05` - Add a bidirectional guard test that a race-losing spawned daemon terminates instead of lingering
- `2026-07-23-service-orphan-reaping-P03-S09` - Add a test that the reap clears a real lingering launcher-daemon orphan pair
- `2026-07-23-service-orphan-reaping-P04-S10` - Reconcile the reap envelope with the broker and control-plane structured-stop regression suite

### plan

- `2026-07-23-service-orphan-reaping-plan` - `service-orphan-reaping` plan

### reference

- `2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference` - `service-orphan-reaping` reference: `launcher-daemon pair origin`

### research

- `2026-07-23-service-orphan-reaping-research` - `service-orphan-reaping` research: `lingering race-loser daemons and their reap`
