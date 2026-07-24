---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Create the torch-free QuiesceGate primitive over a threading.Event with set equals running and clear equals paused, exposing wait, pause, resume and is_paused plus an absorbing-open latch so that once latched open wait returns immediately and pause and clear become no-ops, with positive unit tests that pause blocks a waiter and resume releases it

## Scope

- `src/vaultspec_rag/job_control.py`

## Description

- Add a torch-free `QuiesceGate` class to `src/vaultspec_rag/job_control.py`, placed beside `RunControlToken`, wrapping a `threading.Event` under a `threading.Lock`.
- Adopt the convention set equals running, clear equals paused; construct the gate in the running (unpaused) state by setting the event at init.
- Implement `wait()` as a pure in-kernel park: it returns immediately when latched, otherwise blocks on `Event.wait()` with no timeout, no sleep-poll, and no busy loop.
- Implement `pause()` (clears the event, no-op once latched), `resume()` (sets the event), and `is_paused()` (reports cleared-and-unlatched state; a latched gate is never paused).
- Implement the absorbing-open `latch_open()`: it sets a latch flag and sets the event under the lock, so the open is permanent and wakes any parked waiter; after it, `wait()` short-circuits and `pause()` becomes a no-op.
- Export `QuiesceGate` through `__all__`, keeping the list alphabetically ordered.

## Outcome

Shipped the `QuiesceGate` primitive with API `wait()`, `pause()`, `resume()`, `is_paused()`, and `latch_open()`. The module remains torch-free (stdlib imports only). `NullRunControl` and `NO_RUN_CONTROL` are untouched and stay gateless no-ops. Green gate at this Step: ruff clean on `src tools`, ty clean, basedpyright reports 0 errors.

## Notes

The lock guards only the latch flag plus the pause/latch interplay; `wait()` releases the lock before parking on the Event so a paused gate holds waiters at zero CPU. `resume()` unconditionally sets the event (harmless when already latched open).
