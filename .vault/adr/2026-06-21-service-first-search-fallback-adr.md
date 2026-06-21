---
tags:
  - '#adr'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
related:
  - "[[2026-06-21-service-first-search-fallback-research]]"
---

# `service-first-search-fallback` adr: `service-first search routing; local always explicit, bounded, torn-down` | (**status:** `accepted`)

## Problem Statement

Issue #202: `vaultspec-rag search` can hang far past its `--timeout`, leave
Python processes alive after the caller gives up, and keep the local store
locked for follow-up searches. The research found two coupled defects in the
CLI search router. First, `--timeout` governs only the HTTP service path; once
the command falls through to the in-process local search, that path runs the
full GPU model load and local store open with no deadline. Second, the router
silently enables local execution without operator mandate — it auto-flips the
fallback flag when it merely *discovers* a service port, and it runs local
directly when no service is configured at all. The reporter's hung process held
the store's OS file lock for as long as it stayed alive, and a second search
launched against the same workspace collided, requiring a manual kill.

## Considerations

- The project's intended posture is **service-first by default; local mode is
  always an explicit opt-in** (consistent with the existing `--local-only` /
  `VAULTSPEC_RAG_LOCAL_ONLY` opt-out and the `--allow-fallback` flag). The bug
  is that the router degrades to local *silently* in two places.
- The local search is genuinely heavy (loads three models, opens Qdrant). When
  legitimately invoked it can take tens of seconds; the failure mode is that it
  is invoked when it should not be, and runs without a bound.
- The store lock is correctly OS-scoped (released on process exit). The fix is
  not lock-leak repair but ensuring the command does not hang while holding it,
  and tears down on a deadline/interrupt.

## Constraints

- **Windows-first runtime.** The reporter and the primary dev host are Windows.
  `signal.SIGALRM` is unavailable; a Python thread running the search cannot be
  force-killed. A wall-clock bound on in-process work therefore requires either
  a watchdog that releases the store lock and force-exits the process, or
  running the local search in a child process the parent can terminate.
- A native CUDA-call hang holds the GIL, so a same-process watchdog cannot
  interrupt that specific pathology; only killing the process frees it. The
  watchdog covers the common case (model load latency); the subprocess approach
  is the fully-robust escalation.
- No new third-party dependency; stdlib `threading`/`multiprocessing`/`os` only.

## Implementation

High-level, two layers.

**Layer 1 — service-first routing (removes silent local).** The search router
stops enabling local execution implicitly. The auto-enable of the fallback flag
on port *discovery* is removed. When a service is targeted or discovered but
unreachable, the command exits fast with the existing "service down" envelope
and remediation **unless** the operator has supplied an explicit local mandate.
An explicit mandate is any of: the `--allow-fallback` flag, a dedicated local
opt-in, or the configured local-only mode. With no service and no mandate, the
command does not silently run local — it reports that the service is down and
how to start it or how to opt into local.

**Layer 2 — bounded, torn-down local run.** When local execution *is* mandated,
it runs under a wall-clock deadline derived from `--timeout` (with a sane
default when unset). On expiry the command releases the store lock (closes the
registry slot) and exits non-zero with a clear timeout message, so it never
hangs holding the lock. The deadline is enforced by a watchdog that performs the
teardown and force-exits the process; the heavier child-process isolation is
recorded as the escalation path for the native-hang edge case rather than built
now. Interrupt (Ctrl-C / terminate) follows the same teardown.

## Rationale

Research findings F1 and F2 show the two silent-local entry points and the
unbounded fallback are the proximate cause of every reported symptom; F3 shows
the locked store and orphaned processes are the same live-hung-process fact, so
bounding the run and tearing it down on a deadline resolves them together. F4
(per-socket HTTP budget) is real but secondary and out of this fix's committed
scope. F5 establishes the Windows constraints that make the watchdog +
force-exit the pragmatic bounded mechanism, with subprocess isolation named as
the robust escalation.

## Consequences

- A bare `search` against a down/missing service now fails fast and loud instead
  of silently grinding locally — a deliberate, visible UX change that enforces
  the service-first rule. Operators who want local must say so.
- The reported hang cannot recur: mandated local runs are deadline-bound and
  release the lock on expiry; un-mandated local cannot start.
- Residual: a native CUDA hang during a mandated local run is bounded only by
  process kill, not the in-process watchdog; the subprocess escalation remains
  available if that surfaces. The HTTP per-socket budget (F4) is left for a
  follow-up.

## Codification candidates

- **Rule slug:** `search-is-service-first-local-is-explicit`.
  **Rule:** The CLI search router must never execute the in-process local search
  without an explicit operator mandate (`--allow-fallback`, the local opt-in, or
  configured local-only mode); an unreachable or absent service with no mandate
  exits with the service-down envelope, and any mandated local run is bounded by
  a wall-clock deadline that releases the store lock on expiry.
