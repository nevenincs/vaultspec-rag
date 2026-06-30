---
tags:
  - '#research'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
related: []
---

# `rag-broker-affordances` research: `broker-facing lifecycle affordances: idempotent start and machine-global discovery`

The cross-project service-management audit produced a dashboard handover whose final
section recorded two OPTIONAL rag-side coordination asks - small affordances that make
rag's single-machine service cleaner for an out-of-process broker (the vaultspec-dashboard
engine) to manage. Both are still unaddressed. (1) `server start` is not idempotent for a
broker: when a healthy owned service is already running, the start command exits 1 (the
port and machine-singleton guards trip first), so a broker that speculatively starts rag
sees a gateway fault rather than "already running, attach" - the audit's C1 exit-1->502
flattening at its source. (2) discovery is `service.json` under
`VAULTSPEC_RAG_STATUS_DIR`, with no machine-global pointer: a consumer that does not share
rag's STATUS_DIR (the per-scope-isolation case the machine-lock module already anticipates)
cannot find the one running service, even though the machine lock that guarantees the
singleton is itself STATUS_DIR-independent. This research grounds both rag-side fixes:
make `server start --json` exit 0 with a structured `already_running` envelope, and write a
STATUS_DIR-independent machine-global discovery pointer beside the machine lock.

## Findings

### F1 — `server start` shadows its own idempotent path and emits no JSON

`service_start` (`src/vaultspec_rag/cli/_service_lifecycle.py`) runs its guards in this
order: the port-bindable guard (exit 1 if the port is taken), the machine-lock guard (exit
1 if any live holder owns the machine), the qdrant-binary guard, then
`if _existing_service_running(): return` (exit 0, "Service already running"). Because the
idempotent check is LAST, a healthy owned service on the default port trips the port guard
and exits 1 before the idempotent return is ever reached - the friendly path is shadowed.
The command also has no `--json` option (the dashboard's broker confirms "rag 0.2.25 rejects
`--json` on server-start/stop"), so even the human "already running" message is unparseable.
`_existing_service_running()` already computes the running pid/port and prints the human
lines INLINE, so making it return that info (and moving the printing to the caller) is the
refactor the JSON path needs.

### F2 — The fix is a reorder plus a JSON contract, not new lifecycle machinery

The idempotent check must run FIRST: a healthy owned service (`_existing_service_running`)
is a success (`already_running`, exit 0) before the port/machine guards, which then only
catch the genuine "someone else holds the port" / "another service owns the machine" cases.
In `--json` mode every exit path emits one envelope through the existing `_emit_json`
(`{ok, command, data|error, ...}`): `already_running` (ok, exit 0, pid+port), `started`
(ok, exit 0, pid+port+startup_s), and the failures (`port_in_use`, `machine_owned` with the
holder pid, `daemon_breakaway`, `start_timeout`) as `ok:false` error envelopes exiting
non-zero. Human (non-JSON) output is unchanged. This mirrors the storage verbs' `--json`
discipline (one document per invocation) and the `server status` JSON contract.

### F3 — The machine singleton is STATUS_DIR-independent; discovery is not

`_machine_lock.py` deliberately anchors the lock at
`qdrant_storage_dir.parent / "service.lock"` - beside the machine-global Qdrant storage,
NOT under STATUS_DIR - so the singleton holds even when `VAULTSPEC_RAG_STATUS_DIR` is
overridden (the module's own docstring names "the dashboard's project-local case"). But the
discovery file (`service.json`) lives at `cfg.status_dir`, so a consumer that does not share
rag's STATUS_DIR cannot find the running service, even though the lock proves exactly one
exists and where its storage is. The asymmetry is the gap: the singleton is machine-global,
its discovery is not.

### F4 — The daemon already writes a versioned discovery file; the pointer rides the same tick

The daemon's `_heartbeat_tick_sync` (`src/vaultspec_rag/server/_lifecycle.py`) writes the
discovery file atomically (`.tmp` + `os.replace`) on every heartbeat, carrying a versioned
schema (`SERVICE_DISCOVERY_SCHEMA`/`SERVICE_DISCOVERY_VERSION`, from the
`service-discovery-schema` ADR), the port, token, pid, qdrant pid/port, and the
staleness contract. The machine-global pointer is the SAME payload written a second time to
a fixed STATUS_DIR-independent path beside the lock
(`machine_lock_path().parent / "service.json"`, distinct from the STATUS_DIR file). It is
cleaned on shutdown alongside the existing `_unlink_status_file_silently`. A consumer reads
the machine-global pointer to discover the one service regardless of its own STATUS_DIR.

### F5 — Where the pointer lives, and why beside the lock

`machine_lock_path()` resolves `Path(cfg.qdrant_storage_dir).parent / "service.lock"`; the
pointer beside it (`.../service.json`) is anchored to the same machine-global storage the
lock is, so the two move together and a consumer that can reach the lock can reach the
pointer. In the default config the storage parent is `~/.vaultspec-rag/qdrant-server/`, so
the pointer (`~/.vaultspec-rag/qdrant-server/service.json`) is distinct from the STATUS_DIR
file (`~/.vaultspec-rag/service.json`) - no collision. A new neutral helper
`machine_discovery_path()` (in `_machine_lock.py`, the existing machine-global-path owner)
returns it; a `read_machine_discovery()` reader parses it tolerantly (a missing/stale file
is truthful absence, never an error), mirroring the dashboard's own discovery tolerance.

### F6 — Both are additive and consumer-optional

Neither fix requires a dashboard change to land: `--json` is opt-in (the human path is
untouched), and the machine-global pointer is an ADDITIONAL file (the STATUS_DIR
`service.json` still exists, so every current consumer keeps working). The dashboard can
adopt them later - pass `--json` to its `start_rag_service` and read the `already_running`
envelope; add the machine-global pointer as a discovery candidate - as follow-ups, not
prerequisites. rag ships the capability; the broker opts in.

### F7 — Conventions and placement

- Phase 1 (idempotent start) is `_service_lifecycle.py` + the `_render._emit_json` helper;
  `_existing_service_running` is refactored to return the running pid/port (the caller
  prints/JSONs). Tests assert the reorder (an already-running owned service exits 0 with
  the `already_running` envelope, never the port-guard exit 1) and each `--json` outcome
  shape, using the existing service-CLI test isolation (`VAULTSPEC_RAG_STATUS_DIR` to tmp,
  no ambient state) per the `managed-singleton-paths-isolate-storage-dir-in-tests` and
  `service-tests-isolate-status-dir` rules.
- Phase 2 (discovery pointer) is `_machine_lock.py` (the path + reader) + the daemon
  heartbeat/shutdown write (`server/_lifecycle.py`). Tests set
  `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp path (the managed-singleton isolation rule)
  and assert the pointer is written beside the lock, carries the discovery payload, is
  cleaned on shutdown, and that `read_machine_discovery` tolerates absence.
- `service-domain-owns-operability` and `operator-views-are-bounded` hold: the pointer is
  bounded discovery data, not a new health surface; the CLI/MCP read shared behavior.

### F8 — Scope boundaries

- **In scope:** `server start --json` with the reordered idempotent `already_running` exit
  0 and structured envelopes for every outcome; the machine-global discovery pointer (path
  helper, daemon write on heartbeat + cleanup on shutdown, tolerant reader); tests for both.
- **Out of scope:** changing the human (non-JSON) start output; `server stop --json` (a
  possible sibling follow-up, not asked); the dashboard's adoption of either (follow-ups);
  any change to the machine-lock authority itself (the OS advisory lock is unchanged - the
  pointer is informational discovery, the lock remains the singleton authority).
- **Open question for the ADR:** whether the machine-global pointer reuses the exact
  STATUS_DIR `service.json` schema/payload (simplest; one writer shape) or a trimmed pointer
  (port/token/pid/status_dir only); and whether to also expose a `read_machine_discovery`
  on the public api facade for in-process consumers or keep it in `_machine_lock`.
