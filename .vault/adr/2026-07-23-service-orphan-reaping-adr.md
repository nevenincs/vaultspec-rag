---
tags:
  - '#adr'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:0cf8bf09802271837986d7377d66d223a5ea32172b0eb88507bb0d40178ff64b'
related:
  - "[[2026-07-23-service-orphan-reaping-research]]"
---

# `service-orphan-reaping` adr: `guaranteed daemon self-exit on a failed claim, plus a bounded signature-scoped reap` | (**status:** `accepted`)

## Problem Statement

A resident daemon that loses the machine-singleton race does not terminate its
own OS process, and `server stop` cannot see or reap the survivor, so repeated
`server start` attempts accumulate idle daemons that leave the operator unable to
recover the machine — the failure the production team hit as "rag is down". The
mechanism, the reproduction, and the option space are grounded in
`2026-07-23-service-orphan-reaping-research`. A decision is needed now because the
bug is install-path-agnostic and per-attempt, so every recovery attempt makes it
worse, and because the existing machine-singleton reap does not cover this orphan
class. This record decides the two-part durable fix; it extends, and does not
reverse, `2026-06-24-service-hardware-singleton-adr`.

## Considerations

- The singleton claim raise never reaches the daemon's own `os._exit` backstop,
  so the process wedges at interpreter shutdown rather than exiting (grounding:
  `2026-07-23-service-orphan-reaping-research`). The daemon already owns the exit
  primitive (`_exit_standalone_daemon`); the gap is purely which failures route
  through it.
- `server stop` reaps exactly one target across its three channels
  (pointer/lock/`--port`), so a survivor holding none is invisible (grounding:
  same research). The existing single-target reap is correct for the singleton;
  it is not a reap of surplus processes.
- A blanket signature reap is unsafe: it would kill the live singleton, an
  isolated-config second instance, and unrelated CI/sibling-project daemons
  (grounding: same research, scoped-vs-blanket finding). The machine lock and the
  discovery pointer are the two authoritative "this is the real service" signals.
- Any stop path must keep the broker-facing contract: one structured envelope per
  `--json` exit, an already-satisfied request as success, and an unachieved stop
  as a non-zero fault (rule `broker-facing-cli-outcomes-are-structured-and-idempotent`;
  `2026-07-13-control-plane-affordances-adr`, `2026-06-27-rag-broker-affordances-adr`).
- Operator surfaces stay explicit and bounded, never a silent default that widens
  blast radius (rule `operator-views-are-bounded`).

## Considered options

- **Self-exit A — move the claim inside the lifespan `try` guard (chosen, part 1).**
  The claim failure then routes through the existing `_exit_standalone_daemon(1)`;
  smallest diff, reuses the proven exit path. Requires the release-on-failure
  guard to tolerate a partial/absent lease.
- **Self-exit B — a top-level entrypoint backstop that `os._exit`s on any startup
  exception (chosen, part 1, as defense-in-depth).** Catches the port-bind sibling
  and any future pre-guard failure in one place; coarser but complete.
- **Self-exit C — graceful `sys.exit` instead of `os._exit` (rejected).** A wedged
  worker hangs the interpreter-exit join; this is the exact hang the existing
  `os._exit` backstop was built to skip.
- **Reap X — a bounded `server stop --orphans` flag with a lock/pointer-anchored
  predicate (chosen, part 2).** Explicit, in-domain, composes with the structured
  envelope.
- **Reap Y — reap orphans by default on every `server stop` (rejected).** Re-opens
  the cross-config-kill hazard the current "don't probe the port without a pointer"
  guard exists to avoid.
- **Reap Z — a separate top-level verb (rejected).** Fragments the stop domain and
  duplicates the identity/envelope machinery that already lives in `server stop`.

## Constraints

- No frontier risk: every primitive exists in-tree and mature — `_exit_standalone_daemon`,
  the machine lock (`machine_lock_live_holder`), the discovery pointer, and the
  `_is_our_service` signature. The work is re-routing failures and adding a guarded
  enumeration.
- Parent-feature stability: this builds directly on `2026-06-24-service-hardware-singleton-adr`
  (the machine lock and identity signals) and the structured-stop contract of
  `2026-07-13-control-plane-affordances-adr`; both are `accepted` and shipped, so
  the extension rests on stable ground.
- Cross-platform: self-exit and reap must hold on Windows and POSIX; the signature
  check already has both branches, and `os._exit` is platform-neutral.
- Open reference-phase item before implementation: the exact origin of the
  launcher+daemon pair is unconfirmed (the server module spawns no watchdog), so
  the reap predicate must be validated against the real process tree — the plan's
  reference step must resolve it so the reap handles the pair, not a lone process.

## Implementation

Two independent layers, sequenced so part 1 stops accumulation before part 2
cleans the backlog.

**Part 1 — guaranteed self-exit.** Bring the machine-singleton claim inside the
lifespan startup guard so its failure converges on the same `_exit_standalone_daemon(1)`
the serving and rollback paths already use, and reconcile the release-on-failure
teardown (the discovery publisher and shutdown-hook installation currently
constructed from the lease) to tolerate a claim that never produced a lease. Add
a top-level entrypoint backstop that forces `os._exit` on any startup exception
escaping the run, covering the port-bind sibling and any future pre-guard failure.
The daemon that loses the race then terminates instead of wedging at interpreter
shutdown.

**Part 2 — bounded signature reap.** Add an explicit, opt-in reap path to
`server stop` (a flag, not a default) that enumerates live processes matching the
daemon signature via the existing identity check, and reaps a match only when it
is neither the machine-lock holder nor the discovery-pointer PID — the two
must-never-kill anchors — and never a foreign process or a legitimately isolated
second-config instance. It reaps the launcher+daemon pair together, and reports
through the existing structured-outcome helpers: a distinct terminal status
carrying a reaped count on success (so a broker distinguishes "cleaned N" from
"nothing to do"), and a non-zero fault when a matched orphan refuses to die. The
predicate and the pair handling depend on the reference-phase confirmation named
in Constraints.

## Rationale

Part 1 is the knockout: the accumulation is entirely a missing `os._exit` on one
code path, and the research confirms routing the claim failure through the daemon's
existing exit backstop is sufficient, so the smallest correct change removes the
source of every orphan. Self-exit B is added because the port-bind sibling and any
future pre-guard failure share the same hang, and a single top-level backstop
closes the class rather than one instance. Part 2 exists because part 1 does not
clean daemons already leaked; the lock/pointer-anchored predicate is what lets a
reap be aggressive about surplus processes while provably never touching the real
singleton or an isolated instance — the safety property that a blanket sweep
cannot offer and that the research's scoped-vs-blanket finding requires. Keeping
the reap an explicit flag on `server stop` (not a default, not a new verb) is what
`operator-views-are-bounded` and the structured-stop contract jointly demand.

## Consequences

Gains: `server start`/`server stop` become a genuine recovery loop — a lost race
self-terminates, and an accumulated backlog is reapable without a manual OS kill;
the broker contract gains a `reaped` outcome it can act on. Honest difficulties:
the reap predicate is only as safe as the confirmation that the lock holder and
pointer PID are the sole authoritative anchors, and the launcher+daemon pair's
origin must be nailed in the reference step before the predicate is trusted — a
wrong predicate here kills a live service. `os._exit` on a claim failure skips
`atexit`/`finally`, tolerated because at that point the daemon owns nothing to
clean. Pitfall to avoid: letting the reap creep into the default `server stop`
path, which would reintroduce the cross-config-kill hazard this record explicitly
rejects. Pathway opened: the same signature-enumeration primitive could later back
a `server status --orphans` diagnostic, surfacing accumulation before it wedges a
machine.
