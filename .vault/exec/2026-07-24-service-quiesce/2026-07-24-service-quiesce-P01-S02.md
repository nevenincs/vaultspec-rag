---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S02'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Integrate the gate into RunControlToken as an optional injected reference where request_cancel and request_shutdown latch the gate open, checkpoint consults the gate first but only when protected depth is zero and re-checks absorbing signals after the gate releases, and a gateless token and NullRunControl stay no-op

## Scope

- `src/vaultspec_rag/job_control.py`

## Description

- Give `RunControlToken.__init__` an optional `gate: QuiesceGate | None = None` parameter stored as `self._gate`, so every existing call site and test that constructs a gateless token is unchanged.
- Make `request_cancel()` and `request_shutdown()` also call `latch_open()` on the injected gate under the token lock, so an absorbing request opens the gate irreversibly and a parked worker can never block forever.
- Rework `checkpoint()` to the exact order: take any pending signal first (a no-op inside a protected span, deferring delivery); then, only when the protected depth is zero and a gate is injected, wait on the gate; then re-take the signal so a worker woken by a shutdown or cancel latch raises rather than continuing.
- Leave the gate wait out of `protected()` entirely, so a checkpoint inside an indivisible mutation span never parks under the writer lock.

## Outcome

The token now carries the separate hold-and-resume concern without conflating it with the existing unwinding `ControlRequest.PAUSE`: the gate holds the same attempt in place, the pause signal still unwinds it. A default (gateless) token and `NullRunControl` remain no-op. Absorbing shutdown/cancel win over a concurrent re-pause via the latch. Green gate at this Step: ruff clean on `src tools`, ty clean, basedpyright reports 0 errors.

## Notes

`checkpoint()` reads the protected depth under the lock once and returns before parking when a span is open; the gate is injected only on the daemon service path, so default-token semantics are byte-for-byte unchanged.
