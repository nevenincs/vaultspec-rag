---
generated: true
tags:
  - '#index'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - '[[2026-06-24-service-hardware-singleton-W01-P01-S01]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P01-S02]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P01-S03]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P02-S04]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P02-S05]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P02-S06]]'
  - '[[2026-06-24-service-hardware-singleton-W01-P02-S07]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P03-S08]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P03-S09]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P03-S10]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P04-S11]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P04-S12]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P04-S13]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P04-S14]]'
  - '[[2026-06-24-service-hardware-singleton-W02-P04-S15]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P05-S16]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P05-S17]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P05-S18]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P05-S19]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P06-S20]]'
  - '[[2026-06-24-service-hardware-singleton-W03-P06-S21]]'
  - '[[2026-06-24-service-hardware-singleton-W04-P07-S22]]'
  - '[[2026-06-24-service-hardware-singleton-W04-P07-S23]]'
  - '[[2026-06-24-service-hardware-singleton-W04-P07-S24]]'
  - '[[2026-06-24-service-hardware-singleton-W04-P07-S25]]'
  - '[[2026-06-24-service-hardware-singleton-W04-P08-S26]]'
  - '[[2026-06-24-service-hardware-singleton-adr]]'
  - '[[2026-06-24-service-hardware-singleton-audit]]'
  - '[[2026-06-24-service-hardware-singleton-plan]]'
  - '[[2026-06-24-service-hardware-singleton-research]]'
---

# `service-hardware-singleton` feature index

Auto-generated index of all documents tagged with `#service-hardware-singleton`.

## Documents

### adr

- `2026-06-24-service-hardware-singleton-adr` - `service-hardware-singleton` adr: `one service per machine with verified qdrant attach` | (**status:** `accepted`)

### audit

- `2026-06-24-service-hardware-singleton-audit` - `service-hardware-singleton` audit: `hardening`

### exec

- `2026-06-24-service-hardware-singleton-W01-P01-S01` - Capture the qdrant child stdout and stderr to the log reliably across platforms
- `2026-06-24-service-hardware-singleton-W01-P01-S02` - Report a non-ready child exit with the captured log tail and a named cause
- `2026-06-24-service-hardware-singleton-W01-P01-S03` - Test that a non-ready child surfaces its cause instead of an opaque timeout
- `2026-06-24-service-hardware-singleton-W01-P02-S04` - Add a qdrant port-holder probe reporting whether a managed server is listening
- `2026-06-24-service-hardware-singleton-W01-P02-S05` - Add a storage-lock probe distinguishing a live holder from a dead owner
- `2026-06-24-service-hardware-singleton-W01-P02-S06` - Classify a managed qdrant orphan by expected storage and dead owner pid
- `2026-06-24-service-hardware-singleton-W01-P02-S07` - Unit-test the holder and orphan detection primitives
- `2026-06-24-service-hardware-singleton-W02-P03-S08` - Write a machine-local qdrant identity sidecar on bring-up (storage, version, owner token)
- `2026-06-24-service-hardware-singleton-W02-P03-S09` - Validate the identity signal under local trust for safe attach
- `2026-06-24-service-hardware-singleton-W02-P03-S10` - Unit-test identity write and validation
- `2026-06-24-service-hardware-singleton-W02-P04-S11` - Implement the attach gate: health, version match, storage match, ownership
- `2026-06-24-service-hardware-singleton-W02-P04-S12` - Make supervised start attach-or-spawn using the gate
- `2026-06-24-service-hardware-singleton-W02-P04-S13` - Refuse fast without spawning when a holder fails the attach gate
- `2026-06-24-service-hardware-singleton-W02-P04-S14` - Integration-test attach to a healthy managed qdrant with no second spawn
- `2026-06-24-service-hardware-singleton-W02-P04-S15` - Integration-test refuse-fast on unhealthy, wrong-version, or foreign holder
- `2026-06-24-service-hardware-singleton-W03-P05-S16` - Add a crash-safe machine-scoped service lock under the managed dir
- `2026-06-24-service-hardware-singleton-W03-P05-S17` - Make server start detect an existing healthy machine service and refuse with a pointer
- `2026-06-24-service-hardware-singleton-W03-P05-S18` - Reclaim a stale machine lock held by a dead owner on start
- `2026-06-24-service-hardware-singleton-W03-P05-S19` - Integration-test that a second start refuses and a stale lock is reclaimed
- `2026-06-24-service-hardware-singleton-W03-P06-S20` - Reap a provably-dead managed qdrant orphan before spawning
- `2026-06-24-service-hardware-singleton-W03-P06-S21` - Integration-test that a dead orphan is reaped and a live holder is never killed
- `2026-06-24-service-hardware-singleton-W04-P07-S22` - Adversarial: N concurrent starts yield exactly one service and one qdrant
- `2026-06-24-service-hardware-singleton-W04-P07-S23` - Adversarial: an injected held port or storage lock yields fast-fail or reap, never a competitor
- `2026-06-24-service-hardware-singleton-W04-P07-S24` - Adversarial: an unhealthy or corrupt qdrant holder is refused-attach with a named cause
- `2026-06-24-service-hardware-singleton-W04-P07-S25` - Adversarial: concurrent multi-repo search and index load through one service holds under saturation
- `2026-06-24-service-hardware-singleton-W04-P08-S26` - Run the full hardening gate across unit, integration, and adversarial suites

### plan

- `2026-06-24-service-hardware-singleton-plan` - `service-hardware-singleton` plan

### research

- `2026-06-24-service-hardware-singleton-research` - `service-hardware-singleton` research: `multi-service-instance vs single-hardware contention`
