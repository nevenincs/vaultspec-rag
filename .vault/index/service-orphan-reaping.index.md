---
generated: true
tags:
  - '#index'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - '[[2026-07-23-service-orphan-reaping-P02-S01]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S03]]'
  - '[[2026-07-23-service-orphan-reaping-P02-S04]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S06]]'
  - '[[2026-07-23-service-orphan-reaping-P03-S07]]'
  - '[[2026-07-23-service-orphan-reaping-adr]]'
  - '[[2026-07-23-service-orphan-reaping-plan]]'
  - '[[2026-07-23-service-orphan-reaping-research]]'
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

### plan

- `2026-07-23-service-orphan-reaping-plan` - `service-orphan-reaping` plan

### research

- `2026-07-23-service-orphan-reaping-research` - `service-orphan-reaping` research: `lingering race-loser daemons and their reap`
