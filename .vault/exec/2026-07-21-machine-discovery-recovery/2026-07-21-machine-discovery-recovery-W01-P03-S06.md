---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:88a00a16720655a7d8133085abe355ff7e6bdc0850f40642f181efba6ec463c4'
step_id: 'S06'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Build heartbeat snapshots from daemon-owned state and repair both discovery views independently

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`
- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

- Build each complete discovery snapshot from daemon-owned PID, port, token, phase, start time, interpreter, heartbeat, and supervised-Qdrant state.
- Add a locked canonical status replacement path that does not read or trust the prior status document.
- Publish the status view and machine pointer independently so failure or corruption of one cannot suppress repair of the other.
- Serialize heartbeat publication, phase changes, quiescence, and cleanup in one retained-lease publisher.
- Make quiescence wait behind an in-flight synchronous tick and prevent every later tick from recreating discovery.

## Outcome

Heartbeat recovery no longer depends on an existing or parseable operator status file. A
single daemon-owned snapshot can recreate either view independently, and the publisher's
quiescence gate supplies the ordering primitive needed to prevent shutdown resurrection.

## Notes

The status replacement primitive lives beside the existing cross-process merge lock so
repair remains serialized with launcher writes and deletion. Ruff lint and formatting
passed, BasedPyright reported zero diagnostics, and an isolated real-lock production smoke
proved corrupt-status plus missing-pointer repair, identical payloads, quiescent no-op, and
owner cleanup without touching the operator service. Lifecycle wiring remains assigned to
S07.
