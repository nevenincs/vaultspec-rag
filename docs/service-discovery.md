# Service discovery

The resident background service is a **machine singleton**: exactly one may run per
machine, because it owns the single GPU and the single managed Qdrant. Sibling tools (the
CLI, the MCP server, a supervising broker) locate that service and judge whether it is
alive by reading the discovery records it publishes.

This document is the **consumer-facing contract** for those records: the two discovery
views and where each lives, the versioned schema, who owns the records and how ownership
is proved, the fields a consumer may rely on, and the typed states a consumer must
distinguish — in particular the difference between *no service* and *a live service whose
address cannot be trusted*. Fields not listed under [Interface fields](#interface-fields)
are internal diagnostics and must not be relied upon.

## Authority: the OS machine lock

The single authority for "a service is running on this machine" is an **OS advisory
lock** (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) held on a lock file for the
lifetime of the serving process
(`src/vaultspec_rag/_machine_lock.py:1-24`, `machine_lock_live_holder` at
`src/vaultspec_rag/_machine_lock.py:353-387`). The OS releases it automatically when the
holder dies, so a crashed daemon never strands the lock — there is no stale-file reclaim
heuristic. A discovery file is *evidence* of an address; the live lock is *proof* of
ownership. When the two disagree, the lock wins.

The lock file (`service.lock`) lives beside the machine-global managed Qdrant storage,
not under the per-instance status directory, so it is machine-wide even when
`VAULTSPEC_RAG_STATUS_DIR` is overridden (`machine_lock_path` at
`src/vaultspec_rag/_machine_lock.py:98-103`).

## Two discovery views

The daemon publishes the **same versioned payload** to two files with the same name,
`service.json`, in two different directories. They serve different consumers.

| View                | Location                                                                                                                           | Owned/authoritative                  | Purpose                                                                                                                                    |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Machine pointer** | beside the lock: `{qdrant_storage_dir}/../service.json` (`machine_discovery_path` at `src/vaultspec_rag/_machine_lock.py:106-114`) | Yes — mutated only by the lock owner | The canonical address record. A consumer that does not share the service's `VAULTSPEC_RAG_STATUS_DIR` still finds the one running service. |
| **Status file**     | `{status_dir}/service.json` (`_status_file` at `src/vaultspec_rag/serviceclient/_discovery.py:140-146`)                            | No — operator/compatibility view     | Operator detail, and a legacy fallback for pre-pointer daemons.                                                                            |

`status_dir` is the CLI `--status-dir` override, else the `VAULTSPEC_RAG_STATUS_DIR`
environment variable, else `~/.vaultspec-rag/`.

The status file's deletion or corruption must never prevent the daemon from republishing
canonical discovery: each heartbeat rebuilds a complete daemon-owned snapshot and can
recreate a missing or invalid status file
(`_replace_service_status` at `src/vaultspec_rag/serviceclient/_discovery.py:318-351`).

## Ownership and authenticated publication

The machine pointer is **owner-authenticated**. A caller may publish or delete it only
while it can present the process-local lease returned by a successful lock acquisition
(`MachineLockLease` at `src/vaultspec_rag/_machine_lock.py:76-88`). The publish primitive
verifies that the current process still holds that exact retained lease and that the
payload names the lease-owning PID; a mere PID read or lock probe is not sufficient
authorization (`publish_machine_discovery` at
`src/vaultspec_rag/_machine_lock.py:156-201`, `delete_machine_discovery` at
`src/vaultspec_rag/_machine_lock.py:204-215`). Consequently a non-holder cannot overwrite
or remove canonical discovery even if it reproduces the owner PID.

Publication is atomic: the writer creates a unique temporary file in the destination
directory and `os.replace`s it into place, so a reader never observes a partial document.

The two files differ in on-disk formatting, though both are valid JSON objects a consumer
should parse structurally, not by layout: the machine pointer is written pretty-printed
(`json.dumps(payload, indent=2)`, `src/vaultspec_rag/_machine_lock.py:171`) while the
status-file merge writer emits compact JSON
(`src/vaultspec_rag/serviceclient/_discovery.py:311`).

### Status-file write serialization

Startup writers to the **status file** serialize through an OS-backed
`service.json.lock` (`_status_write_lock` at
`src/vaultspec_rag/serviceclient/_discovery.py:191-224`): either the launching CLI or the
daemon may publish first, and the later writer merges rather than erasing fields already
published by the other process. The daemon's same-port lifecycle publication is
authoritative — on Windows the PID of a virtual-environment launcher may differ from the
serving daemon's PID, so once the daemon has stamped `phase`, a delayed parent write
preserves the daemon PID, the first `started_at`, and the managed-Qdrant identity
(`_apply_status_merge_policy` at
`src/vaultspec_rag/serviceclient/_discovery.py:227-273`).

## Version discriminator

Every file carries a schema discriminator
(`src/vaultspec_rag/serviceclient/_discovery.py:31-32`). Pin on the pair and refuse a file
you do not understand:

| Field     | Type    | Value                   |
| --------- | ------- | ----------------------- |
| `schema`  | string  | `vaultspec.rag.service` |
| `version` | integer | `1`                     |

`version` is bumped only on a breaking shape change, and this document is updated in the
same change. Additive fields do not bump the version.

A reader that does not understand the pair must refuse the file, and this project's own
client enforces the pin rather than only writing it: a file declaring a `schema` or
`version` this build does not recognise is refused, and none of its remaining fields are
read on the assumption that they mean what this reader expects. A file declaring
*neither* is the pre-discriminator case and is accepted; the next daemon heartbeat
upgrades it in place. A file declaring one half without the other is a partial write and
is refused.

Where the refused file is the machine pointer of a live lock holder, the resolution is
`degraded` with reason `pointer_incompatible`, never `absent`: something owns the
singleton, and reporting it as stopped would invite a caller to start a second daemon.

Do not confuse this pair with `package_version`. The pair describes the *shape of this
file*; `package_version` describes the *release of the daemon that wrote it*. A client
compares the pair to decide whether it can read the file at all, and `package_version` to
decide whether it may drive the service it points at.

## Interface fields

| Field                  | Type            | Format / meaning                                                                                                                                 |
| ---------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `schema`               | string          | Schema discriminator (see Version discriminator).                                                                                                |
| `version`              | integer         | Schema version (see Version discriminator).                                                                                                      |
| `pid`                  | integer         | OS process id of the serving daemon. See the PID-reuse caveat below.                                                                             |
| `port`                 | integer         | TCP port the service listens on (loopback).                                                                                                      |
| `started_at`           | string          | Service start time, **ISO-8601 with UTC offset, second precision** (e.g. `2026-06-24T10:23:52+00:00`).                                           |
| `last_heartbeat`       | string          | Time of the last heartbeat write, **same format as `started_at`**. Drives the staleness check.                                                   |
| `heartbeat_interval_s` | integer         | Seconds between heartbeat writes.                                                                                                                |
| `stale_after_s`        | integer         | Age in seconds past which `last_heartbeat` is considered stale.                                                                                  |
| `service_token`        | string          | Per-process identity token; also echoed by the ungated `/health` route for identity verification.                                                |
| `package_version`      | string          | `vaultspec-rag` release of the writing process. Also on `/health` and `/readiness`. A client compares it to its own and refuses a mismatch.      |
| `python_version`       | string          | Interpreter version of the writing process (e.g. `3.13.11`). Informational; not a compatibility gate.                                            |
| `phase`                | string          | Daemon lifecycle phase: `warming` before readiness or `running` after startup completes (`src/vaultspec_rag/serviceclient/_discovery.py:42-44`). |
| `qdrant_pid`           | integer or null | PID of the witnessed managed Qdrant child. Null means no witnessed managed child is available.                                                   |
| `qdrant_alive`         | boolean or null | Whether the supervised Qdrant child is alive.                                                                                                    |
| `qdrant_port`          | integer or null | Port of the supervised Qdrant child.                                                                                                             |
| `qdrant_version`       | string          | Pinned managed-Qdrant version witnessed by the daemon.                                                                                           |
| `qdrant_start_time`    | number          | OS creation time of the witnessed Qdrant child, epoch seconds. Binds `qdrant_pid` to one process incarnation.                                    |
| `qdrant_identity`      | object          | Complete managed-child witness: `pid`, `start_time`, `port`, `version`, `storage_path`.                                                          |

The `qdrant_*` fields are present only in managed-server mode. In local-only mode, and
when the service targets a remote Qdrant URL, the daemon supervises no child, so the
fields are absent rather than null. Treat absent and null alike.

Both timestamp fields use one declared format — ISO-8601 with a UTC offset at second
precision — emitted by a single shared helper so they never diverge
(`_discovery_timestamp` at `src/vaultspec_rag/serviceclient/_discovery.py:104-114`). The
offset is always UTC (`+00:00`). Parse them as ISO-8601; do **not** assume an epoch
number.

## Staleness contract

The daemon rewrites `last_heartbeat` every `heartbeat_interval_s` seconds. A consumer
should treat the service as **stale / not live** when
`now - last_heartbeat > stale_after_s`. Read both thresholds from the file rather than
hard-coding them; a consumer that reads a pre-upgrade payload omitting `stale_after_s`
falls back to a 60-second window
(`src/vaultspec_rag/serviceclient/_discovery.py:49`, `_staleness_window_seconds` at
`src/vaultspec_rag/serviceclient/_discovery.py:431-440`).

**PID-reuse caveat.** A recorded `pid` may, after a crash without clean shutdown, belong
to an unrelated process. Do not treat a live `pid` alone as proof the service is up.
Combine it with a fresh `last_heartbeat`; where stronger proof is needed, verify the
`service_token` against the target port's `/health` response.

## Typed resolution: ready, absent, degraded

A consumer must not reduce discovery to "is there a port?". `resolve_machine_service`
returns one typed, evidence-carrying verdict
(`MachineResolution` at `src/vaultspec_rag/serviceclient/_discovery.py:443-491`;
`resolve_machine_service` at
`src/vaultspec_rag/serviceclient/_discovery.py:494-585`) whose `state` is exactly one of
three values (`src/vaultspec_rag/serviceclient/_discovery.py:57-59`):

- **`ready`** — a live lock holder has published a schema-valid, fresh pointer whose PID
  matches the holder. `port` carries a usable address.
- **`absent`** — no machine lock is held, so nothing is running. Only in this case is the
  status-file legacy fallback consulted (`_status_file_resolution` at
  `src/vaultspec_rag/serviceclient/_discovery.py:588-622`).
- **`degraded`** — a live holder owns the singleton, but its published pointer cannot be
  trusted. This is deliberately **distinct from `absent`**: something owns the singleton,
  so a consumer must not render it as stopped, must not fall back to a status-file
  address the owner never published, and must not start a second daemon (which would only
  lose the race).

A `degraded` verdict carries a `reason` naming the specific disagreement
(`src/vaultspec_rag/serviceclient/_discovery.py:63-67`):

| `reason`               | Meaning                                                                                  |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| `pointer_missing`      | Live holder, but no pointer file.                                                        |
| `pointer_invalid`      | Pointer present but its port is unreadable/malformed.                                    |
| `pointer_stale`        | Pointer's `last_heartbeat` is older than its staleness window.                           |
| `pointer_foreign`      | Pointer names a PID other than the live holder — a leftover from a previous incarnation. |
| `probe_failed`         | The machine lock or pointer could not be inspected at all.                               |
| `pointer_incompatible` | Pointer declares a `schema`/`version` pair this build does not implement.                |

The verdict also preserves `holder_pid`, `pointer_pid`, `port`, `service_token`,
`heartbeat_age_s`, and `stale_after_s` as evidence, and `source` records which view
supplied the address (`machine_pointer`, `status_file`, or `none`;
`src/vaultspec_rag/serviceclient/_discovery.py:70-72`). A `status_file`-sourced `ready`
verdict is a labelled legacy compatibility result, valid only because no live holder
exists.

## Canonical operator status

CLI, HTTP, and MCP adapters render one canonical operator verdict composed from the typed
resolution plus already-probed liveness signals — the service domain owns operability, so
the verdict is derived once and rendered per surface, never recomputed
(`compose_discovery_status` at `src/vaultspec_rag/serviceclient/_status.py:171-267`). The
operator states and their exit codes
(`src/vaultspec_rag/serviceclient/_status.py:35-48`):

| Operator state       | Meaning                                                                                    | Exit code |
| -------------------- | ------------------------------------------------------------------------------------------ | --------- |
| `running`            | Serving normally.                                                                          | 0         |
| `warming`            | Holds the singleton, loading models, not yet serving.                                      | 5         |
| `stopped`            | Nothing is running (resolution `absent`).                                                  | 3         |
| `crashed`            | A recorded service is not serving (dead PID, reused PID, silent port, or stale heartbeat). | 4         |
| `degraded_discovery` | Live holder, untrustworthy pointer (resolution `degraded`).                                | 4         |

`degraded_discovery` rides the existing exit code 4 rather than introducing a new code a
supervising broker would have to learn. The structured status body (shared by every
adapter) carries a `discovery` block with the resolution's state, source, both PIDs, port,
heartbeat age, staleness window, reason, and a one-line `evidence` string
(`DiscoveryStatus.as_dict` at
`src/vaultspec_rag/serviceclient/_status.py:113-139`).

Service-dependent operations fail fast on a degraded resolution rather than guessing an
address; read-only status returns the complete observation.

## Reconcile

A degraded machine cannot be repaired by a consumer: the singleton owner is the only
process permitted to publish or delete its pointer. The only correct repair is the
owner's own next heartbeat. `vaultspec-rag server reconcile` waits, boundedly, for that
convergence and reports what it saw (`service_reconcile` in
`src/vaultspec_rag/cli/_service_reconcile.py`; `reconcile_discovery` in
`src/vaultspec_rag/serviceclient/_status.py`).

The command is **non-destructive and idempotent**. It never writes discovery, never
deletes a record, and never stops, restarts, or terminates a process, so it is safe to
run speculatively against a healthy machine. It re-resolves on an interval until the
timeout (default 35 s, roughly two heartbeat intervals), and succeeds only when the serving
daemon's identity agrees across every axis the pointer claims — holder PID, pointer PID,
freshness, port, service token, and the live `/health` response
(`_identity_confirmed` in `src/vaultspec_rag/serviceclient/_status.py`).

Outcomes (`src/vaultspec_rag/serviceclient/_status.py:274-276`):

- **`already_converged`** — discovery agreed on the first look. Exit 0.
- **`converged`** — the owner's heartbeat repaired it within the bound. Exit 0.
- **`unresolved`** — it did not converge in time, or nothing holds the singleton. The
  remaining degraded evidence is returned. Exit 1.

Reconcile never invents an address or terminates a process; a wedged owner remains
degraded, and the operator sees that state rather than a guessed recovery.
