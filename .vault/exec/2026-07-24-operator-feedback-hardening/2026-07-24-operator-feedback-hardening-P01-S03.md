---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:9e5204916e998fa6b9ebfc10422d4e086203822e3099b53eeffb69ce669c7531'
step_id: 'S03'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Report every start pre-flight stage and the daemon cold-start phases

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Announce the command before any probe that can block.
- Name each pre-flight stage: the running-service check, the port and machine-singleton guard, the qdrant binary check and first-use download, the GPU probe, and the spawn.
- Refresh the wait every poll with the daemon's published phase and the elapsed time.

## Outcome

A cold start reports continuously from its first statement. Verified on the reporting machine: the announce, all five pre-flight stages, then the daemon's own phases including a determinate model count, with elapsed advancing while the phase did not.

## Notes

The daemon had been publishing those phases and that count since the previous feature shipped; nothing had ever displayed them. The log path is announced once rather than repeated, because it is too long for a line that refreshes every few seconds and an operator wants it to tail a slow start.
