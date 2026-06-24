---
tags:
  - '#research'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---

# `service-hardware-singleton` research: `multi-service-instance vs single-hardware contention`

The resident RAG service manages a single machine's hardware - one GPU and one managed
Qdrant server - yet the service-instance architecture (per-port, per-token, per-status-dir,
per-root) permits several service instances to run on that one machine. When more than one
instance starts, they contend for the singular Qdrant (a fixed port plus a single-writer
RocksDB storage directory) and the singular GPU. This was hit live: after a clean
`server stop` + `server start`, the Qdrant child failed its readiness wait
("qdrant server on port 8765 failed to become ready within 300s") and the service stayed
down. This document maps the seat/token/parallelism/root-override/storage-override
architecture, characterizes the tension precisely, and proposes concrete mitigations.
Grounded by reading the service lifecycle, the Qdrant supervisor, and the config resolution,
and by reproducing the failure.

## Findings

### F1 - The Qdrant server is a machine singleton by construction

The supervisor (`src/vaultspec_rag/qdrant_runtime/_supervise.py`) spawns one loopback child
bound to a fixed HTTP port (`http_port = cfg.qdrant_port`, default 8765) with storage at a
fixed, machine-global path (`cfg.qdrant_storage_dir`, default
`~/.vaultspec-rag/qdrant-server/storage` - under `$HOME`, not per-project). Qdrant's storage
is RocksDB-backed, which holds a single-writer lock on that directory. So the Qdrant server
is inherently one-per-machine: one port, one storage, one writer.

Crucially, `QdrantSupervisor.spawn()` and `start_supervised_from_config()` perform **no
pre-flight check** for an already-listening Qdrant on `cfg.qdrant_port` and **no check** that
the storage directory's lock is free. They unconditionally spawn a new child and poll
`/readyz` for up to 300s. If a healthy Qdrant is already serving that port/storage (from
another service instance, or an orphan that outlived a daemon), the new child cannot open the
locked storage and never becomes ready - surfacing as the opaque 300s timeout rather than a
clear "already in use / attach instead" outcome.

### F2 - The service-start guard is port-scoped, not machine-scoped

`service_start` in `src/vaultspec_rag/cli/_service_lifecycle.py` guards only the **service
port**: `_port_is_available(port)` (default 8766) plus `_existing_service_running()` which
matches an existing healthy service via `_is_our_service(pid, port, expected_token)` against
the status file. This correctly prevents two services racing on the *same* port. It does
**not** prevent a second service on a *different* port, and it does not consult the Qdrant
singleton at all. Two services on ports 8766 and 8777 both pass this guard, then both call
`start_supervised_from_config()` and both try to own Qdrant 8765 + the shared storage - F1's
contention.

### F3 - Service-instance identity is per (port, token, status-dir, root)

Each service instance is identified by a `service_token` (uuid4 written to
`{status_dir}/service.json`, returned from `/health`) and reached by port. The status
directory is itself overridable (`VAULTSPEC_RAG_STATUS_DIR`); a known consumer - the
dashboard's embedded RAG service - uses a *project-local* status dir
(`.vault/data/engine-data/`), so its `service.json`, token, and discovery are entirely
separate from the default `~/.vaultspec-rag/` instance. That is exactly the multi-instance
condition: two services, two tokens, two status dirs, two ports - and one Qdrant singleton
they both assume they may spawn. The token/port machinery scales service *identity* but does
nothing to arbitrate the shared hardware.

### F4 - The intended multi-tenancy is multi-PROJECT within ONE service, not multi-SERVICE

The service is designed to host many projects inside a single instance: a project "seat"
model (`service_max_projects`, default 16), per-root leases in the `ServiceRegistry`,
idle-eviction (`service_idle_ttl_seconds`), and per-request `project_root` so one daemon
serves many roots. Parallelism is likewise bounded *within one instance*: two capacity
limiters (`search_concurrency` = 16, `index_job_concurrency` = 4) and the single GPU consumer
plus the global GPU lock. Every one of these mechanisms assumes a single resident process
owning the machine's GPU and Qdrant. The architecture's answer to "many projects on one
machine" is *one service, many seats* - not *many services*. The multi-service condition is
therefore outside the intended design, but nothing structurally forbids it.

### F5 - Override knobs that enable (or could resolve) the tension

The relevant resolution knobs (`src/vaultspec_rag/config.py`): service port (`--port` /
`VAULTSPEC_RAG_PORT`), status dir (`VAULTSPEC_RAG_STATUS_DIR`), project root (`--target` /
`VAULTSPEC_RAG_ROOT` and per-request `project_root`), per-project local data
(`data_dir`, `VAULTSPEC_RAG_DATA_DIR`), the machine-global server storage
(`qdrant_storage_dir`, `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`), and the Qdrant port
(`qdrant_port`, `VAULTSPEC_RAG_QDRANT_PORT`). Two observations: (a) `data_dir` is per-project
(correct - local-mode stores are independent), but `qdrant_storage_dir` and `qdrant_port` are
machine-global, so overriding the *service* port without also overriding the *Qdrant* port
and storage is precisely what produces two services fighting over one Qdrant; (b) these knobs
are also the levers for a fix - a second instance could be made to attach to the existing
Qdrant rather than spawn its own.

### F6 - Reproduced failure mode, with confirmed root cause

`server stop` then `server start` (server mode) failed with the readiness timeout. Direct
investigation found two compounding causes, both consequences of the singleton architecture:

1. **An orphaned Qdrant process held the singleton.** A `qdrant.exe` (PID 69552, ~5 GB
   resident) from a prior service instance was still alive, holding port 8765 and the shared
   storage. Every new `server start` spawned a child that could not bind the port / open the
   locked storage and so never readied - the opaque timeout. The Windows kill-on-close Job
   Object is supposed to prevent exactly this, yet an orphan survived (the prior daemon's
   death path did not tear the child down), and the supervisor has no pre-flight detection of
   an already-running Qdrant. Killing the orphan was necessary to recover.

2. **A corrupt collection panics the whole server.** Running the Qdrant binary directly with
   the supervisor's env reproduced a hard Rust panic (exit 101) while *loading* the collection
   `r0b2bd3608445_codebase_docs`. Because the storage is one shared machine-global store, a
   single root's corrupt collection takes down RAG for **every** root on the machine.
   Quarantining that one collection let the server load the remaining ~88 collections.

After killing the orphan and quarantining the corrupt collection, server mode started cleanly
(94s cold-load of the remaining collections) and a live search returned correct,
intent-ranked results. The binary itself is healthy (`qdrant --version` succeeds); the
supervisor's log redirect did **not** capture the panic (the log showed nothing), which is
why the failure presented as an opaque timeout rather than a clear "collection X panicked" /
"port already held by pid N" message.

Two structural facts this confirms: the shared store accumulated ~45 projects' collection
pairs (90 collections) under one home-dir path - the multi-root singleton accumulating
unbounded across every worktree the operator has indexed - and a single bad member or a
single orphan is a whole-machine outage.

### F7 - Service discovery diverges from the running service

After the clean server-mode start, `server status` reported "stopped" while the service
answered correctly on `--port 8766`. Discovery resolves the service through the status file
in the (overridable) status dir; when the running instance's recorded identity/port does not
match what the CLI reads, the operator sees a false "stopped". This is the same
status-dir/token keying that lets multiple instances exist (F3): identity is per-status-dir,
so discovery is only as correct as the status-dir the caller happens to read. It compounds
the tension - an operator cannot even reliably tell whether a service (and thus a Qdrant
owner) is already running before starting another.

## Proposed mitigations (for an ADR to weigh)

- **P1 - Qdrant attach-not-spawn (smallest, highest-leverage).** Before spawning, probe
  `cfg.qdrant_port`: if a healthy Qdrant of the expected version is already serving, ATTACH to
  it (treat it as the shared machine singleton) instead of spawning a competitor. This makes a
  second service instance reuse the one Qdrant rather than deadlock on its storage lock, and it
  makes restart graceful when an old Qdrant is still up. Requires distinguishing "our managed
  Qdrant" from an unrelated process on that port.

- **P2 - Storage-lock / orphan detection with a fast, clear failure.** When the storage lock
  is held (or the port is occupied by a non-attachable process), fail in seconds with an
  actionable message naming the holder, instead of a 300s opaque timeout. Optionally reap a
  provably-dead managed orphan (stale lock + dead owner PID) before spawning.

- **P3 - Machine-level service singleton (the architectural fix).** Treat the resident service
  as one-per-machine: a second `server start` on any port detects an existing healthy service
  (across status dirs, e.g. via a machine-scoped lock or registry) and either refuses with a
  pointer to the running instance or attaches to it. The intended multi-tenancy
  (`service_max_projects`, per-root leases) already covers "many projects on one machine," so a
  second resident process is the thing to prevent.

- **P4 - Make the Qdrant singleton explicit in the model.** Decouple "service instance"
  (identity: port + token + status dir) from "machine hardware owner" (the GPU + the one
  Qdrant). Either elect one instance as the hardware owner that others route through, or
  formally document that running a second server-mode instance is unsupported and gate it.

- **P5 - Guardrail for the override foot-gun.** If `--port` (service) is overridden without a
  corresponding free `qdrant_port`/`qdrant_storage_dir`, warn or refuse, since that is the
  exact configuration that yields two services contending for one Qdrant.

- **P6 - Contain a bad collection; surface the real error.** A single corrupt collection must
  not take down RAG for every root (F6). Options: detect-and-quarantine a collection that
  fails to load (start degraded, report it) rather than letting the panic abort startup; and
  fix the supervisor's log capture so the child's panic/stderr actually reaches `qdrant.log`
  (today it was lost, producing an opaque timeout instead of "collection X panicked"). The
  shared-storage blast radius also motivates revisiting whether per-root collections should be
  isolatable.

- **P7 - Trustworthy discovery + bounded accumulation.** Make `server status` reflect the
  actually-running instance regardless of status-dir drift (F7), and bound the shared store's
  growth - ~45 stale projects' collections had accumulated; eviction/pruning of collections
  for roots that no longer exist keeps the singleton from growing unbounded and shrinks the
  cold-load time (94s here) and the corrupt-member blast radius.

## Open questions for the ADR

- Is the target end-state "one Qdrant shared by N service instances" (P1/P2) or "one service
  per machine" (P3)? They are complementary but imply different amounts of work.
- How is "our managed Qdrant" identified for safe attach (a version probe is necessary but not
  sufficient - an ownership/identity signal is needed)?
- How should the dashboard's project-local-status-dir instance participate - attach to the
  shared Qdrant (P1) or be folded into a single machine service (P3)?
- What is the migration/back-compat story for hosts already running with overridden ports?
