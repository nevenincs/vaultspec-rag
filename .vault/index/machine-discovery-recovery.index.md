---
generated: true
tags:
  - '#index'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S01]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S02]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S03]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-summary]]'
  - '[[2026-07-21-machine-discovery-recovery-adr]]'
  - '[[2026-07-21-machine-discovery-recovery-plan]]'
  - '[[2026-07-21-machine-discovery-recovery-reference]]'
  - '[[2026-07-21-machine-discovery-recovery-research]]'
  - '[[2026-07-21-machine-discovery-recovery-s01-test-isolation-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s02-containment-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s03-isolation-tests-audit]]'
---

# `machine-discovery-recovery` feature index

Auto-generated index of all documents tagged with `#machine-discovery-recovery`.

## Documents

### adr

- `2026-07-21-machine-discovery-recovery-adr` - `machine-discovery-recovery` adr: `owner-authenticated, self-healing service discovery` | (**status:** `accepted`)

### audit

- `2026-07-21-machine-discovery-recovery-s01-test-isolation-audit` - `machine-discovery-recovery` audit: `W01.P01.S01 singleton test isolation`
- `2026-07-22-machine-discovery-recovery-s02-containment-audit` - `machine-discovery-recovery` audit: `W01.P01.S02 containment guard`
- `2026-07-22-machine-discovery-recovery-s03-isolation-tests-audit` - `machine-discovery-recovery` audit: `W01.P01.S03 managed singleton isolation regressions`

### exec

- `2026-07-21-machine-discovery-recovery-W01-P01-S01` - Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary
- `2026-07-21-machine-discovery-recovery-W01-P01-S02` - Enforce the session-owned containment root before singleton writes and process control whenever pytest is active
- `2026-07-21-machine-discovery-recovery-W01-P01-S03` - Prove ambient and in-test path changes cannot redirect singleton writers into a test-owned trap outside the session root
- `2026-07-21-machine-discovery-recovery-W01-P01-summary` - `machine-discovery-recovery` `W01.P01` summary

### plan

- `2026-07-21-machine-discovery-recovery-plan` - `machine-discovery-recovery` plan

### reference

- `2026-07-21-machine-discovery-recovery-reference` - `machine-discovery-recovery` reference: `ownership, resolution, and recovery seams`

### research

- `2026-07-21-machine-discovery-recovery-research` - `machine-discovery-recovery` research: `self-healing owner-authenticated discovery`
