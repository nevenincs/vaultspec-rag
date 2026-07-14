---
derived_from:
  - "audit:2026-07-13-control-plane-affordances-audit"
---

# Broker-facing CLI outcomes are structured and idempotent

## Rule

A lifecycle CLI verb a broker drives (`server start`, `server stop`) must, in
`--json` mode, emit exactly ONE structured envelope on every exit path -
success and each failure - and treat an already-satisfied request as a success
(exit 0 with an `already_*` status), never a non-zero fault a broker would
misread as a gateway error. An outcome that leaves the requested state
unachieved (a stop that leaves the service running) is a failure and exits
non-zero in BOTH human and json modes.

## Why

The `2026-06-27-rag-broker-affordances-adr` shipped `server start --json`
after a supervising broker misread "already running" as an opaque 502; the
`2026-07-13-control-plane-affordances-adr` completed the sibling
`server stop --json`. The candidate held through both execution cycles: a
broker can speculatively start (attach on `already_running`) and stop
(no-op on `already_stopped`), and the one genuine stop failure
(`identity_unconfirmed`, service left running) is a visible exit 1 instead
of a silent success.

## How

- **Good:** `_start_success`/`_fail_start` and `_stop_success`/`_fail_stop`
  in `src/vaultspec_rag/cli/_service_lifecycle.py` - every terminal branch
  converges on exactly one helper; `{ok, command, data:{status,...}}` on
  success, `{ok:false, command, error, message, data}` on failure.
- **Good:** `server stop` with nothing to stop emits `already_stopped`
  (exit 0); terminating outcomes carry initiator attribution fields.
- **Bad:** printing human text on a `--json` path, emitting zero or two
  envelopes on any exit, or exiting 0 from a stop that skipped a live
  unconfirmed process.
