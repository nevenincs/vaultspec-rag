---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S08'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Add guard tests that the reap never targets the singleton, a foreign process, or an isolated-config instance

## Scope

- `src/vaultspec_rag/tests/test_service_stop_port.py`

## Description

- Spawn real launcher+worker witness pairs (a venv shim makes each
  `-m vaultspec_rag.server --port <port>` spawn a two-process pair) on isolated
  status/storage dirs and a unique port, then reap OUT-OF-PROCESS via
  `python -m vaultspec_rag server stop --orphans --port <port> --json`.
- Prove the launcher-pointer case: with the launcher recorded as the
  discovery pointer, the whole singleton pair is spared, the whole orphan pair
  is reaped, and a daemon on a different port is never enumerated.
- Prove the worker-pointer case: with the worker (the child that runs the
  lifespan, as production publishes) recorded as the pointer, the shim launcher
  is spared via the protect-parent branch.
- Prove the machine-lock case: a singleton that holds the lease but published
  no pointer is spared by the lock anchor alone (no-pointer recovery scenario).

## Outcome

The reap is proven never to target the live singleton pair, a foreign-port
daemon, or (via the /health-port anchor added in the P04 review) an
isolated-config instance sharing the port. All three anchor sources -
discovery pointer, machine-lock holder, and live port holder - and both lineage
branches are covered. Guard-tests-prove-they-can-fail: the protect-parent,
protect-child, and lock-holder anchors each turn a spare assertion RED when
removed from the reap's anchor set, and restore to green - recorded in the
commit bodies. Ran out-of-process to eliminate the self-anchor confound that an
in-process reap introduces (the reaper would parent the witness daemons). ruff,
basedpyright, and the citation gate clean.

## Notes

The reap MUST run out-of-process in these tests: an in-process reap makes
`os.getpid()` the sentinels' parent, so the self-anchor masks the
pointer/lineage protection and the mutation-proof does not bite. Landed across
commits `98ad4441` (safety restructure + the P04 /health-anchor HIGH fix) and
`0bb27b12` (the machine-lock anchor case).
