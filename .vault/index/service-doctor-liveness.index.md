---
generated: true
tags:
  - '#index'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - '[[2026-06-24-service-doctor-liveness-W01-P01-S01]]'
  - '[[2026-06-24-service-doctor-liveness-W01-P01-S02]]'
  - '[[2026-06-24-service-doctor-liveness-W01-P01-S03]]'
  - '[[2026-06-24-service-doctor-liveness-W01-P02-S04]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P03-S05]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P03-S06]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P04-S07]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P04-S08]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P05-S09]]'
  - '[[2026-06-24-service-doctor-liveness-W02-P05-S10]]'
  - '[[2026-06-24-service-doctor-liveness-adr]]'
  - '[[2026-06-24-service-doctor-liveness-audit]]'
  - '[[2026-06-24-service-doctor-liveness-plan]]'
  - '[[2026-06-24-service-doctor-liveness-research]]'
---

# `service-doctor-liveness` feature index

Auto-generated index of all documents tagged with `#service-doctor-liveness`.

## Documents

### adr

- `2026-06-24-service-doctor-liveness-adr` - `service-doctor-liveness` adr: `doctor reports live service truth; flapping is diagnosed before it is fixed` | (**status:** `accepted`)

### audit

- `2026-06-24-service-doctor-liveness-audit` - `service-doctor-liveness` audit: `doctor live-truth + flapping remediation review (PASS)`

### exec

- `2026-06-24-service-doctor-liveness-W01-P01-S01` - Add a live-service axis to server doctor that reads the discovery file and probes health and port, reusing the status-path liveness truth
- `2026-06-24-service-doctor-liveness-W01-P01-S02` - Report ready:false or an explicit degraded/needs-restart status when the daemon is dead, keeping the installed-dependency axis present and labelled so the two are never conflated
- `2026-06-24-service-doctor-liveness-W01-P01-S03` - Reflect the real live qdrant runtime state in the doctor output rather than the binary-on-disk default that reads ready when no supervisor exists in-process
- `2026-06-24-service-doctor-liveness-W01-P02-S04` - Add a no-mock test asserting doctor reports a not-ready or degraded live status with no daemon running while still reporting dependency readiness truthfully
- `2026-06-24-service-doctor-liveness-W02-P03-S05` - Instrument and reproduce the spawn-without-breakaway fallback to confirm whether the daemon survives the launching shell exit on this host
- `2026-06-24-service-doctor-liveness-W02-P03-S06` - Instrument and reproduce the identity-miss discovery-file unlink to confirm whether a concurrent status or start can delete a live daemon's discovery file
- `2026-06-24-service-doctor-liveness-W02-P04-S07` - Make daemon survival independent of the launching shell: on a breakaway denial, detach so the daemon outlives the parent or fail loudly instead of the silent doomed fallback
- `2026-06-24-service-doctor-liveness-W02-P04-S08` - Unlink the discovery file only when the holder is confirmed dead, never on an ambiguous identity result, so a transient health or PID miss cannot delete a live service's file
- `2026-06-24-service-doctor-liveness-W02-P05-S09` - Add a no-mock test that a daemon survives a simulated parent-shell exit on this platform
- `2026-06-24-service-doctor-liveness-W02-P05-S10` - Add a no-mock test that a concurrent lifecycle command does not unlink a live daemon's discovery file on a transient identity miss

### plan

- `2026-06-24-service-doctor-liveness-plan` - `service-doctor-liveness` plan

### research

- `2026-06-24-service-doctor-liveness-research` - `service-doctor-liveness` research: `doctor truth and daemon flapping`
