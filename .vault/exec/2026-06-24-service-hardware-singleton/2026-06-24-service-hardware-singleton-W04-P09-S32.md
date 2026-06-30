---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S32'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Harden the ownership proof against owner-pid reuse (record and re-verify a process start-time or per-owner nonce in the identity) so a recycled owner pid is not misclassified as a live managed_running owner (review MEDIUM-3)

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Harden the ownership proof against owner-pid reuse so a recycled owner pid is
  not misclassified as a live `managed_running` owner.
- Add an `owner_start_time` field to the identity record (the process creation
  time, the anti-pid-reuse witness; `0.0` for legacy records).
- Add `pid_start_time`, reading the process creation time via psutil, and
  `owner_pid_is_live_owner`, which confirms a live owner only when the pid is
  alive and its recorded creation time matches the live process's.
- Capture the owner start time at identity write time (resolved from the owner
  pid by default) and parse it back on read.
- Route `classify_qdrant_state` through `owner_pid_is_live_owner` so a live but
  start-time-mismatched owner classifies as `managed_orphan`, not
  `managed_running`.
- Add tests covering the witness read, matching/mismatched/legacy/dead cases, and
  the classification consequence (recycled pid reaped, not attached).

## Outcome

A recycled owner pid no longer reads as a live managed owner: a listening server
whose recorded owner pid is alive but whose start time differs classifies as a
managed orphan to be reaped, never attached to or competed with. Legacy records
without a recorded start time degrade to the prior pid-only check, so the change
is backward compatible. Identity write/read round-trips the new field.

## Notes

Data safety already held via the health/version/storage gates; this closes the
ownership-proof gap the audit flagged as MEDIUM-3. psutil is an existing project
dependency, so no new requirement was introduced.
