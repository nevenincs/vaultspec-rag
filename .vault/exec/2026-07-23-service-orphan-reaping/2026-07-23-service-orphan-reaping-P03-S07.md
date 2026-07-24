---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S07'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Wire the opt-in server stop --orphans flag with its structured reaped-count success and refusal-fault envelope

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- Add `_expected_singleton_port` resolving the reap scope: explicit `--port`,
  else the discovery-pointer port, else the configured default.
- Add the opt-in `--orphans` flag to `server stop` and a body branch that
  reaps via `_reap_orphan_daemons` and returns before the normal stop logic.
- Emit the broker-facing structured envelope: a `reaped` count on success and an
  `orphan_reap_incomplete` non-zero fault when a matched daemon will not die.

## Outcome

`server stop --orphans` is an explicit, bounded recovery that clears accumulated
orphans while sparing the live singleton, isolated-config, and foreign daemons,
emitting exactly one structured outcome per exit. ruff, ty, basedpyright clean.
Landed with S06 in commit `eb669da3`.

## Notes

Opt-in, never a default, per the operator-views-are-bounded rule - a default
reap would reintroduce the cross-config-kill hazard. The guard tests proving the
predicate and the pair reap (S08/S09) run in the GPU-free daemon-spawning
window.
