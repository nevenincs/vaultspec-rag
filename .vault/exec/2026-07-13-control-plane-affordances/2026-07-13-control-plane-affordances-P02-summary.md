---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:7ec7fbc40c9344617d142d62bc0b17202205f262d5583bc5ad41c78e207d2bd4'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# `control-plane-affordances` `P02` summary

Both Steps complete (S05 implementation, S06 tests), one commit per Step.

- Modified: `src/vaultspec_rag/cli/_service_lifecycle.py`
- Created: `src/vaultspec_rag/tests/test_cli_server_stop.py`

## Description

`server stop` gained `--json` with the same envelope machinery as start
(`_stop_success` / `_fail_stop`, command tag `service.stop`): exactly one
structured envelope per exit path. Satisfied outcomes are `ok:true` exit 0 -
`stopped`, `already_stopped` (the idempotent success, both the default and
`--port` variants), `cleaned` (stale discovery file for a confirmed-dead
pid), and `reclaimed` (machine-singleton holder terminated). The
identity-unconfirmed skip, the one outcome that leaves a service running, is
`ok:false identity_unconfirmed` and now exits 1 in BOTH human and json modes
\- the ADR-approved breaking change from the previous exit 0.

Verification: eleven new tests pin every envelope shape, the human-mode
no-JSON guarantee, and the live wiring for the stageable outcomes; the
existing stop-port, singleton-reclaim, and CLI suites pass unchanged (368
CLI+server unit tests green). Notable incident: the first staging of the
unconfirmed-identity case used a python sleeper child, which the tokenless
executable-name identity fallback confirmed as ours - the resulting
terminate sent CTRL_BREAK to the shared Windows process group and killed
the pytest run; the committed test spawns a non-python child and documents
the trap. This completes the second execution cycle of the
`broker-facing-cli-outcomes-are-structured-and-idempotent` codification
candidate.
