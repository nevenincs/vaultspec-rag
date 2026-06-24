---
tags:
  - '#research'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---

# `service-doctor-liveness` research: `doctor truth and daemon flapping`

GitHub issue **#204** reports two lifecycle gaps observed after a failed or crashed
`server start`, plus a third symptom. (1) `server doctor --json` reports `ready: true, server_mode: true` with all dependencies `ready` while the daemon is dead, and at the same
time its qdrant runtime block reads `{"mode":"local","url":null,"pid":null,"alive":null, "port":null}` - nothing is actually running. (2) A crashed daemon leaves an orphaned qdrant
and an empty/stale discovery file with no cleanup. (3) The daemon "flaps": it comes up
healthy and then, minutes later with no explicit stop, is gone. Concern (2) - orphan reap and
failed-start cleanup - is being addressed by the landed machine-singleton hardening campaign
and its discovered follow-ups; this research scopes the **residual**: the doctor's
false-ready (concern 1) and the daemon flapping (concern 3). It is grounded in a read-only
code investigation of the doctor and lifecycle paths and feeds an ADR. No implementation here.

## Findings

### F1 - `server doctor` never probes the live daemon; `ready` is installed-dependency truth only

`server doctor` calls `get_readiness()` and emits its `ready` field directly as the JSON
envelope's success flag. It makes no `/health` call, no port probe, and no discovery-file
read - there is no live-daemon signal in the doctor path at all. `get_readiness()` delegates to
a process-wide `compute_readiness()` that is explicitly documented as safe to call before the
runtime is up: it describes installed dependencies, not a running service. `ready` is
`all(dep.status == READY)` over exactly three dimensions - torch CUDA usable, the model repos
present in the HF cache, and a qdrant binary resolvable on disk.

### F2 - The qdrant dimension reads READY on `alive is None`, which is always the case in a CLI process

`compute_readiness()` reads the qdrant runtime via `runtime_state()`, which returns a live
supervisor's state only when a process-global active supervisor is set - and that is set only
inside the daemon's own lifespan. In a CLI `doctor` process the supervisor is always absent,
so `runtime_state()` falls through to a `mode="local", alive=None` block (exactly the reported
null block). The qdrant readiness helper then treats `alive is None` as READY ("no child
supervised in this process; the binary is provisioned and usable"), so the qdrant dimension
reads READY purely because the binary file exists. `server_mode: true` comes from a static
config read (`effective_server_mode()` = qdrant-server default on, not local-only) with no
awareness of any running daemon. The two reported facts (`ready:true` and the null `local`
qdrant block) are produced by the same code and are internally consistent - just structurally
blind to the daemon.

### F3 - The live-state truth exists, but only on the `server status` / `/health` path

The signal that would catch a dead daemon - the live health payload that degrades when the
supervised qdrant is not alive, the discovery-file read, the port-listening probe, the
PID-identity check - lives in the `server status` lifecycle path, not in `server doctor`. So
the fix is not to compute new truth but to make `doctor` consult the live-service truth that
already exists (or to clearly separate "dependencies installed and ready to start" from
"a service is currently running and healthy").

### F4 - Flapping candidate (HIGH): the daemon is spawned inside the launching shell's Windows Job Object

The daemon spawn attempts `CREATE_BREAKAWAY_FROM_JOB`, but on an `OSError` (commonly: the
VS Code integrated terminal, Windows Terminal, and CI runners deny breakaway) it silently
falls back to spawning *without* breakaway, logging only a warning. The daemon then remains a
member of the parent shell's Job Object and the OS terminates it when that shell or terminal
closes - minutes after a healthy start, with no explicit stop. This is the highest-confidence
match to the reported symptom. A Job-kill is not a graceful exit, so no cleanup hook runs.

### F5 - Flapping candidate (HIGH): a concurrent CLI command unlinks a live daemon's discovery file on an identity-check miss

Several lifecycle paths (`_existing_service_running`, the start failure paths, and the status
state computation) unlink the discovery file whenever the identity/liveness signals do not line
up. The identity check (`_is_our_service`) combines a `/health` token round-trip and a PID
heuristic. If that check misfires transiently - a `/health` token fetch that times out, or a
PID-reuse false negative - a routine `server status` or second `server start` from another
process can delete the running daemon's discovery file even though the daemon is alive,
producing the reported "discovery file not found while the service was up".

### F6 - Flapping candidate (HIGH): machine-lock scope versus per-worktree status dirs

The machine-singleton lock is machine-global (derived from the shared qdrant storage parent),
while the discovery file is status-dir-scoped (and the status dir is overridden per worktree).
A second daemon started under a different status dir (a different worktree, like this one) has
a different discovery file but contends for the same machine lock; its lifespan aborts before
yielding when the lock is held. The interaction of two daemons over one machine lock and one
qdrant port/storage is a flapping vector when worktrees or projects overlap on one machine.

### F7 - Flapping candidate (MEDIUM): a pre-yield lifespan failure unlinks the just-written discovery file

The CLI parent writes the discovery file *before* the daemon's lifespan finishes booting. If
the lifespan then fails after that point but before yielding (a slow/failed qdrant readiness,
a model-load failure under GPU contention), the lifespan `finally` records a clean shutdown and
unlinks the discovery file - so an intermittent boot failure presents as a healthy-looking
start followed by disappearance. (This overlaps the machine-singleton campaign's own discovered
follow-up about releasing the lock on a pre-yield failure.)

### F8 - Ruled out: the heartbeat is a victim, not the dropper

The heartbeat loop swallows all non-cancellation exceptions and never deletes the discovery
file; its tick returns early if the file is already gone. So the heartbeat is not a cause of
the disappearance - it stops updating once the file is gone or the process dies, which is a
symptom, not the trigger.

## Options weighed (for the ADR)

- **Doctor truth.** Option A (recommended): keep `compute_readiness()` as the pre-runtime
  "dependencies ready to start" axis, and add a distinct live-service axis to `doctor` (read
  the discovery file + probe `/health`/port), so the operator-facing top line reflects whether
  a service that is *expected* to be running actually is - reporting `ready:false` or a
  `degraded`/`needs-restart` status when the daemon is dead. Option B: fold liveness into
  `compute_readiness()` - rejected, it is intentionally process-wide and pre-runtime and is
  reused where a daemon must not be assumed.
- **Flapping.** The candidates are several and must be confirmed before they are fixed: the
  plan should diagnose (instrument the spawn-without-breakaway path and the identity-miss
  unlink path, reproduce on this host) before remediating. Likely remediations, per confirmed
  cause: make daemon survival independent of the launching shell (an alternative detach that
  outlives the parent, or a loud failure instead of a doomed silent fallback); never unlink a
  discovery file on an *ambiguous* identity result (unlink only on confirmed-dead); and
  reconcile the machine-lock-vs-status-dir interaction with the singleton campaign owners.

## Open questions for the ADR

- The doctor top-line semantics: when no service is expected (a pure pre-install check), should
  `doctor` still report dependency readiness as `ready:true`? Proposed: yes, but label the live
  axis explicitly so the two are never conflated.
- Which flapping causes are in scope for this pipeline versus owned by the machine-singleton
  campaign (F6, and the pre-yield unlink F7 overlap) - coordinate to avoid double-fixing.
- Whether the Job-Object breakaway fallback should hard-fail or detach differently, and how to
  prove the daemon survives a parent-shell exit in a no-mock test on this platform.
