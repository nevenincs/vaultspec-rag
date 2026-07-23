---
tags:
  - '#research'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
related: []
---

# `service-orphan-reaping` research: `lingering race-loser daemons and their reap`

**Question:** why do `uv tool`/`uvx`-started resident daemons that lose the
machine-singleton race stay alive yet invisible to `server stop`, and what is
the durable fix? **Stakes:** the operator cannot recover the machine — repeated
`server start` attempts accumulate idle daemons, `server stop` reports success
while they persist, and the only escape is a manual OS kill. **Conclusion of the
evidence:** the singleton claim happens *outside* the daemon's guaranteed-exit
guard, so a lock-contention failure never reaches the `os._exit` hook and the
process lingers; and `server stop` reaps exactly one target (the current lock/
port/pointer holder) across all three of its channels, so any surplus daemon
matches none and survives. The fix has two independent halves — guarantee
self-exit on a failed claim, and add a signature-scoped reap of all resident
daemon processes — each of which the ADR must settle separately, with the reap
half carrying the real safety design (never kill a foreign or a legitimately
distinct process). Reproduced on the dev workstation: many live
`python -m vaultspec_rag.server` processes where the singleton must be one. The
orphans hold no port, no lock, no pointer, and — confirmed via
`nvidia-smi --query-compute-apps` — no CUDA context. The bug is NOT
`uvx`-specific: it reproduces across install paths (confirmed from the `uvx`
archive cache AND from a plain project `.venv` in the sibling `vaultspec-core`
worktree), and each `server start` retry adds a fresh launcher+daemon pair
(e.g. pids 40900→14440, then 45216/14512 spawned by a later retry), so
accumulation is per-attempt and install-path-agnostic.

## Findings

### The singleton claim is raised outside the guaranteed-exit guard (root cause of accumulation)

`_service_lifespan` calls `_claim_machine_singleton()` at
`src/vaultspec_rag/server/_lifespan.py:284`, *before and outside* the `try:` at
`:306`. Only that `try` block routes a startup failure to
`_exit_standalone_daemon(1)` (`:364`), which calls `os._exit(code)` gated on
`_m._daemon_process` (`:208`, `:232`, `:253`). `_claim_machine_singleton` raises
`RuntimeError` when another process already holds the machine lock
(`_lifespan.py:64-70`). Because that raise originates before line 306, it never
reaches `_exit_standalone_daemon(1)`; it propagates out of the lifespan
`@asynccontextmanager` to uvicorn's ASGI-lifespan startup handler, which logs
"Application startup failed", stops serving, and RETURNS from `uvicorn.run`
(`src/vaultspec_rag/server/_main.py:185`) rather than exiting. `main()`'s
`finally` (`_main.py:193-200`) then runs and `main` returns — but
`_m._daemon_process` was already set `True` at `_main.py:182`, and
`_exit_standalone_daemon`'s whole reason to exist is that a normal
return-from-`main` interpreter exit HANGS on the interpreter-exit executor join
when a `to_thread`/pool worker is wedged (`_lifespan.py:176-181`, `:227`,
`:332-335`). The clean-serving and guarded-failure paths force `os._exit` to
skip that join; the pre-`try` claim failure skips the `os._exit`, so the process
reaches interpreter shutdown and wedges there — a live process owning nothing.
That confirms option (a) below (move the claim inside the `try` guard) is
sufficient: it routes the claim failure through the same `_exit_standalone_daemon(1)`
the serving path already relies on. The port-bind failure is a sibling (uvicorn
fails to bind, `run` returns, same missing-`os._exit`). Not yet verified: the
exact wedged thread (candidate: the daemon log-capture drain installed at
`_main.py:146` before the claim) and the exact uvicorn version's
lifespan-exception behaviour (`uvicorn@?` — pin during ADR).

### Each failed start leaks a launcher+daemon PAIR, and the leak is install-path-agnostic

Every `server start` retry leaves TWO lingering `python -m vaultspec_rag.server`
processes in a parent→child relation (observed 40900→14440; a later retry added
45216/14512), and the pattern reproduces from the `uvx` archive cache, the
`uv tool` versions dir, AND a plain project `.venv` (the sibling
`vaultspec-core` worktree showed the same launcher+daemon pairs). Two
consequences for the fix: (a) it is a lifecycle defect of the daemon itself, not
a `uvx`-packaging artifact, so the self-exit fix must live in the server, not in
a launcher wrapper; (b) the reap and self-exit must both account for the *pair*,
not a single process. The pair's exact origin is NOT yet confirmed and is a
reference-phase question: the server module spawns no watchdog child
(`src/vaultspec_rag/server/__main__.py` is a thin `-m` entrypoint with no
subprocess, and `_lifespan.py` spawns only the Qdrant supervisor child, never a
second `vaultspec_rag.server`), so the second `vaultspec_rag.server` in the pair
is most likely the `server start` launcher process itself re-materialised under
the detached-spawn/console-reattach path (`cli/_process.py:757` `_spawn_windows`
uses `DETACHED_PROCESS` + a new process group) rather than a daemon-spawned
watchdog — confirm the parent's argv and role in the reference before the ADR
commits a reap predicate that assumes one process per orphaned service.

### `server stop` reaps exactly one target across three channels; surplus daemons match none (root cause of invisibility)

`server stop` resolves its victim through, in order: the discovery-pointer PID
(`_read_service_status`), else the machine-lock holder via
`_reclaim_machine_singleton()` (`src/vaultspec_rag/cli/_service_stop.py:60-87`),
else — only with an explicit `--port` — the `/health` identity holder via
`_stop_service_on_port` (`:309-359`). All three resolve to the *one* current
singleton (the pointer names it, the lock names it, the port is bound by it). A
lingering race-loser is in none of those roles, so `server stop` with no
`--port` returns `already_stopped` (`:447-452`) — and it deliberately does NOT
probe the port without a pointer to avoid misreporting another config's healthy
service as this one's orphan (`:444-446`). The reap is therefore single-target
by construction; nothing enumerates the process table for surplus daemons.

### The existing reap (`service-hardware-singleton`) covers a different orphan class

The prior decision reaps a *provably-dead managed Qdrant* child and a stale
machine-lock holder (D3 of the ADR), and mandates the lock "be released reliably
on crash" — see `.vault/adr/2026-06-24-service-hardware-singleton-adr.md:48`,
`:77-84`, `:116-118`. That covers a dead owner's leftovers, not a *live but idle*
`server` process that never acquired the lock. The new class is the inverse of
what D3 anticipated: not a dead holder to clean up, but a living non-holder that
should never have survived its own failed claim. The fix extends this ADR rather
than superseding it; the machine-lock and identity primitives it built
(`_machine_lock.machine_lock_live_holder` at `_machine_lock.py:353`,
`_is_our_service` at `src/vaultspec_rag/cli/_process.py:116`) are the reap's
building blocks.

### A self-exit fix is cheap and low-risk; the option is *where* to force exit

The daemon already owns the exact primitive: `_exit_standalone_daemon`
(`_lifespan.py:208`) performs the `os._exit` and is a no-op off the standalone
daemon (gated on `_m._daemon_process`, set in `cli/_main.py` before
`uvicorn.run`). Options the ADR must choose between: (a) move the
`_claim_machine_singleton()` call *inside* the `try:` guard so its failure flows
through the existing `_exit_standalone_daemon(1)` — smallest diff, but the lease
must exist before the discovery publisher and shutdown hooks are constructed
(`:285-289`), so the guard's teardown must tolerate a `None`/partial lease; (b)
wrap the whole `__main__`/`uvicorn.run` in a top-level guard that `os._exit`s on
any startup exception — coarser but catches the port-bind sibling and any future
pre-`try` failure in one place; (c) both. `os._exit` (not `sys.exit`) is the
established choice for the standalone daemon because a wedged periodic worker
would otherwise hang the interpreter-exit executor join (`:227`, `:332-335`);
this is consistent with the stdio shim's own `os._exit` for the same class
(`:217`). Graceful `sys.exit` is rejected for the daemon for that documented
reason. Trade-off: `os._exit` on a *claim* failure skips `atexit`/`finally`, but
at that point the daemon owns no lock, no Qdrant child, and no discovery pointer,
so there is nothing to clean — the release-on-failure guard's concerns
(`:295-301`) do not apply pre-claim.

### The signature reap must distinguish "surplus" from "foreign" and from "legitimately distinct"

`_is_our_service(pid)` with no port/token (`cli/_process.py:116-207`) confirms a
process is *a* vaultspec-rag daemon — Windows checks the executable image
contains `"python"` (`:190-191`); POSIX checks `/proc/{pid}/cmdline` contains
`"vaultspec_rag"` (`:196-197`). The daemon is always spawned as
`[interpreter, "-m", "vaultspec_rag.server", ...]` (`cli/_process.py:503-506`),
so both checks match a `uvx`-spawned daemon (its interpreter is an ephemeral uv
cache `python.exe`, still "python"; its cmdline still carries the module). That
signature is necessary but NOT sufficient for a reap decision: it cannot by
itself distinguish (i) a surplus race-loser to kill, from (ii) the real
singleton to preserve, from (iii) a legitimately distinct instance an operator
ran with an isolated `--port`/`STATUS_DIR`/`QDRANT_STORAGE_DIR` (the multi-config
case the existing `--port`-scoped stop and the `_refuse_terminate_from_unisolated_test`
guard at `_service_stop.py:110-139` already respect). The ADR must decide the
safety predicate: candidate is "reap a signature-matched daemon only when it does
NOT hold the machine lock AND is NOT the discovery-pointer PID AND (is bound to
no port OR is bound to the machine-default port while a different process holds
the lock)". The lock holder and pointer PID are the two must-never-kill anchors;
membership in the process table alone is never license to kill. Not investigated:
whether a per-daemon launch token (already minted at `_lifespan.py:279` and
passed as `--launch-token`, seen in the pid-48944 cmdline) could tag "surplus
from this operator's start attempts" vs. "unrelated", giving a tighter predicate
than lock/port/pointer negation.

### Composition with the broker-facing structured/idempotent stop contract

A reap-orphans path must uphold the existing stop envelope contract: exactly one
structured `{ok, command, data:{status,...}}` on every `--json` exit path, an
already-satisfied request as success, and a stop that leaves the target running
as a non-zero fault (the `broker-facing-cli-outcomes-are-structured-and-idempotent`
rule; `.vault/adr/2026-07-13-control-plane-affordances-adr.md` and
`2026-06-27-rag-broker-affordances-adr.md`). The reap therefore needs its own
terminal statuses (candidate: a `reaped` count on success, distinct from
`stopped`/`already_stopped`/`reclaimed`) so a broker reading `--json` can tell
"cleaned N orphans" from "nothing to do", and any orphan that refuses to die must
surface as a non-zero fault, not a silent success. Whether the reap is a new flag
on `server stop` (`--orphans`/`--all`) or a distinct verb is an ADR call;
`operator-views-are-bounded` argues for it being explicit and bounded, not a
default that a routine `server stop` silently performs (a default reap would
re-introduce the cross-config-kill hazard that `:444-446` exists to avoid).

### Scoped vs. blanket recovery, and the VRAM finding (operational, informs urgency not design)

The immediate operational recovery is a signature sweep, but a *blanket*
`pkill -f vaultspec_rag.server` is unsafe while any legitimate daemon runs: on
the dev box it would kill the real singleton (pid 48944,
`…\uv\tools\versions\vaultspec-rag\…python.exe -m vaultspec_rag.server --port 8766`),
the CI runner's daemons under `C:\actions-runner-vaultspec-rag\_work\`, and 8
`vaultspec-core` test daemons — hence recovery must be scoped by explicit PID to
the confirmed orphans. Confirmed the orphans hold no GPU: pids 40900/14440 are
absent from `nvidia-smi --query-compute-apps`, i.e. they raised at the machine
claim (`_lifespan.py:284`) before torch/CUDA load, so they eat no VRAM and pose
no OOM risk to a concurrent GPU run. This bounds the harm (idle CPU processes,
not GPU squatters) and confirms the accumulation is pre-model-load, reinforcing
that the fix belongs at the claim site.

## Sources

- `src/vaultspec_rag/server/_lifespan.py:64-70` — `_claim_machine_singleton` raises on contention
- `src/vaultspec_rag/server/_lifespan.py:208-253` — `_exit_standalone_daemon` (`os._exit`, `_daemon_process` gate)
- `src/vaultspec_rag/server/_lifespan.py:284` — the claim call, outside the `try:` guard
- `src/vaultspec_rag/server/_lifespan.py:306-365` — the startup `try/except` that routes failure to `_exit_standalone_daemon(1)`
- `src/vaultspec_rag/cli/_service_stop.py:60-87` — `_reclaim_machine_singleton`
- `src/vaultspec_rag/cli/_service_stop.py:110-139` — `_refuse_terminate_from_unisolated_test`
- `src/vaultspec_rag/cli/_service_stop.py:309-359`, `:444-452` — `_stop_service_on_port`, the "no pointer → don't probe port" branch
- `src/vaultspec_rag/cli/_process.py:116-207` — `_is_our_service` signature check
- `src/vaultspec_rag/cli/_process.py:503-506` — daemon spawn argv `[interpreter, -m, vaultspec_rag.server]`
- `src/vaultspec_rag/_machine_lock.py:353-388` — `machine_lock_live_holder`
- `.vault/adr/2026-06-24-service-hardware-singleton-adr.md:48`, `:77-84`, `:116-118` — the existing (dead-Qdrant/lock) reap and lock-release-on-crash mandate
- `.vault/adr/2026-07-13-control-plane-affordances-adr.md`, `.vault/adr/2026-06-27-rag-broker-affordances-adr.md` — structured/idempotent stop contract
- GitHub issue #256 — reproduction evidence (10 daemons; uv-cache pids 40900/14440)
- `nvidia-smi --query-compute-apps=pid,used_memory` — orphans absent → no CUDA context
