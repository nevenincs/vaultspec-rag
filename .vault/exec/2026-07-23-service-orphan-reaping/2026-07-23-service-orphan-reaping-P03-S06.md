---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Add the daemon-signature enumeration and the lock-and-pointer-anchored reap predicate

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- Add `_orphan_daemon_pids` enumerating `vaultspec_rag.server` daemons via
  `psutil.process_iter`, matching the resident-daemon launch witness `-m vaultspec_rag.server --port <port>` (any launch token).
- Add `_reap_orphan_daemons` applying the safety predicate: reap a match only
  when it is not the machine-lock holder, not the discovery-pointer pid, and
  not this process, re-confirmed via `_is_our_service` and reaped by
  `_terminate_and_confirm` (which runs the unisolated-test refusal guard).

## Outcome

The reap targets only same-port race-losers; the port witness structurally
excludes isolated-config and foreign-worktree daemons (different port), and the
lock/pointer anchors spare the live singleton. ruff, ty, basedpyright clean and
the reap functions are complexity-clean. Landed with S07 in commit `eb669da3`.

## Notes

The port-witness match assumes the launcher partner in the launcher+daemon pair
also carries `--port`; P01 confirms this and the match is refined there if not.
The global complexity gate is red on another session's uncommitted
`_store_writes.py` (unrelated to this change).
