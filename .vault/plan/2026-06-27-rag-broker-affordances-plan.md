---
tags:
  - '#plan'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-27-rag-broker-affordances-adr]]'
  - '[[2026-06-27-rag-broker-affordances-research]]'
---

# `rag-broker-affordances` plan

Make rag's single-machine service broker-friendly: an idempotent JSON `server start` and a STATUS_DIR-independent machine-global discovery pointer.

### Phase `P01` - idempotent server start with structured JSON outcomes

Reorder the idempotent check ahead of the guards and add a --json contract emitting one envelope per outcome (ADR D1, D2).

- [x] `P01.S01` - Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S02` - Reorder service_start so the idempotent already-running check precedes the port and machine guards; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S03` - Add the --json option and emit one envelope per outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway, start_timeout); `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S04` - Unit-test the reorder and each --json outcome shape with an isolated temp status dir; `src/vaultspec_rag/tests/test_cli_server_start.py`.

### Phase `P02` - machine-global discovery pointer beside the lock

Add the machine-global pointer path and reader, write it on the daemon heartbeat, and clean it on shutdown (ADR D3, D4).

- [x] `P02.S05` - Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module; `src/vaultspec_rag/_machine_lock.py`.
- [x] `P02.S06` - Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P02.S07` - Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir; `src/vaultspec_rag/tests/test_machine_discovery.py`.

## Description

Deliver the two rag-side broker affordances the cross-project audit's handover recorded,
per the accepted ADR. Phase P01 makes `server start` broker-friendly in
`_service_lifecycle.py`: `_existing_service_running` is refactored to return the running
pid/port (the caller prints or JSON-emits), the idempotent check is reordered ahead of the
port and machine guards (so a healthy owned service is `already_running`/exit 0, not the
shadowed port-guard exit 1), and a `--json` option emits one `_emit_json` envelope per
outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway,
start_timeout). Phase P02 adds a STATUS_DIR-independent discovery pointer: a
`machine_discovery_path()` + tolerant `read_machine_discovery()` in `_machine_lock.py`, the
daemon `_heartbeat_tick_sync` writing the versioned discovery payload to it beside the lock
(atomic `.tmp` + `os.replace`) and the shutdown hooks cleaning it. Both are additive
(human start output and the STATUS_DIR file are untouched) and consumer-optional; the
dashboard adopts them as follow-ups. Grounded in the `rag-broker-affordances` research and
ADR; closes the audit's C1 (exit-1 flattening, at the source) and C3 (STATUS_DIR-coupled
discovery) on the rag side.

## Steps

## Parallelization

P01 and P02 touch different files (`_service_lifecycle.py` vs `_machine_lock.py` +
`server/_lifecycle.py`) and are independent, but they share the managed-singleton test
isolation, so they are executed sequentially for a clean review. Within P01, S01 (the
return-refactor) precedes S02 (the reorder) and S03 (the --json branch), with S04 (tests)
last. Within P02, S05 (path + reader) precedes S06 (the daemon write), with S07 (tests)
last. The test steps (S04, S07) gate their phase's completion.

## Verification

The plan is complete when every Step is closed and these criteria hold:

- An already-running healthy owned service makes `server start` exit 0 with the
  `already_running` outcome (the reorder), never the port-guard exit 1 it produced before
  (unit test with an isolated temp status dir).
- `server start --json` emits exactly one `_emit_json` envelope on every exit path:
  `already_running`/`started` (ok, exit 0) and `port_in_use`/`machine_owned`/
  `daemon_breakaway`/`start_timeout` (ok:false, non-zero); the human (non-JSON) output is
  unchanged (unit tests).
- The genuine guard cases still fail: a foreign process holding the port and another
  service owning the machine each still exit non-zero (not mistaken for our service).
- `machine_discovery_path()` resolves beside the machine lock (STATUS_DIR-independent), and
  the daemon heartbeat writes the versioned discovery payload there; shutdown cleans it
  (unit tests with an isolated temp storage dir).
- `read_machine_discovery()` returns the payload when present and tolerates a missing/
  unreadable file as truthful absence, never raising (unit test).
- `just ci` (lint, basedpyright at zero, the unit suite) is green; `vaultspec-core vault check all` stays clean.
