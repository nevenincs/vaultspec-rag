---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S09'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a --local-only flag to server start that selects the local backend and reframe the existing --qdrant flag as the redundant explicit-server opt-in

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Add a first-class `--local-only` boolean flag to the `server start` command that
  selects the on-disk local store as the explicit opt-out of the now-default
  managed Qdrant server backend.
- Reframe the existing `--qdrant/--no-qdrant` flag's help text to describe it as the
  redundant explicit-server opt-in: server mode is already the default, and
  `--local-only` is the selection knob for the local store.
- Thread the `local_only` flag value into the `_spawn_service` call so the daemon
  env carries it (the env translation itself lives in S10's `_process.py` change).

## Outcome

- `server start` now exposes `--local-only`; the flag defaults to `False` and is a
  dedicated knob, not an overload of `--qdrant`. `--qdrant` keeps its tri-state
  `bool | None` semantics but its help now names `--local-only` as the way to select
  the on-disk store.
- The `_spawn_service(..., local_only=local_only)` call wires the flag to the daemon
  env path; combined with S10 the unset flag (`False` default) is still passed
  through as an explicit value, while an operator who wants the default server mode
  simply omits `--local-only`.
- `ruff check` and `ty check` clean on `src/vaultspec_rag/cli/_service_lifecycle.py`
  for the staged hunks; `vaultspec-rag server start --help` renders `--local-only`
  (persona check recorded under S11/S12).

## Notes

Shared-worktree contention: this Step shares `_service_lifecycle.py` with a
concurrent agent reworking the `server status` surface (Health->Readiness relabel)
and with the W01.P02 agent. Three executors committed against one git index
simultaneously. The S09 source hunks (flag, `--qdrant` reframe, spawn-call wiring)
were swept into the W01.P02 agent's commit when that agent ran a whole-file `git add`
while these uncommitted hunks coexisted in the working tree; the S09 code therefore
landed in a sibling commit rather than its own. The code in HEAD is correct and
complete (the `--local-only` flag, the reframed `--qdrant` help, and
`_spawn_service(local_only=local_only)` are all present and verified against this
record). This exec record is committed separately. The `--local-only` flag is a
dedicated `bool` knob defaulting `False`, not an overload of `--qdrant`, per the
locked design.
