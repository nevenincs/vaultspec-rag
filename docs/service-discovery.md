# Service discovery

The resident background daemon is a machine singleton: exactly one may run per machine, because it owns the single GPU and the single managed Qdrant server. Sibling tools locate that daemon, and judge whether it is alive, by reading the discovery records it publishes. Those tools are the command-line interface (CLI), the Model Context Protocol (MCP) server, and any supervising broker. For what the daemon itself does, see the [architecture overview](architecture.md).

This document is the consumer-facing contract for those records. It covers:

- the two discovery views and where each lives
- the versioned schema
- who owns the records and how ownership is proved
- the fields you may rely on
- the typed states you must distinguish

The last of those matters most: the difference between no daemon and a live daemon whose address cannot be trusted.

Fields not listed under [Interface fields](#interface-fields) are internal diagnostics. Don't rely on them.

Throughout, *the daemon* is the serving process, *the machine pointer* and *the status file* are the two records, and *a consumer* is any tool reading them.

## Resolving a daemon

The contract below decomposes into one ordered procedure. A consumer resolves a daemon by:

1. Probing the machine lock. A live holder is proof that something owns the singleton.
1. Reading the machine pointer. Falling back to the status file only when no lock is held.
1. Validating the `schema` and `version` pair, and refusing a record it does not understand.
1. Checking freshness: `now - last_heartbeat` against `stale_after_s`.
1. Confirming the pointer's `pid` matches the lock holder.

Each step has its own section. The result is one of three [typed states](#typed-resolution-ready-absent-degraded).

## Version discriminator

Every record carries a schema discriminator. Pin on the pair and refuse a record you don't understand:

| Field     | Type    | Value                   |
| --------- | ------- | ----------------------- |
| `schema`  | string  | `vaultspec.rag.service` |
| `version` | integer | `1`                     |

A breaking shape change bumps `version`, and the same change updates this document. Additive fields don't bump it.

A consumer that doesn't understand the pair must refuse the record. This project's own client enforces the pin rather than only writing it: it refuses a record declaring a `schema` or `version` this build doesn't recognize, and reads none of the remaining fields on the assumption that they mean what it expects.

A record declaring neither is the pre-discriminator case. Accept it; the next heartbeat upgrades it in place. A record declaring one half without the other is a partial write. Refuse it.

Don't confuse this pair with `package_version`. The pair describes the shape of the record; `package_version` describes the release of the daemon that wrote it. Compare the pair to decide whether you can read the record at all, and `package_version` to decide whether you may drive the daemon it points at.

## Interface fields

Both views carry the same payload. "Presence" says when a field is absent.

| Field                  | Type    | Presence            | Meaning                                                                                                   |
| ---------------------- | ------- | ------------------- | --------------------------------------------------------------------------------------------------------- |
| `schema`               | string  | always              | Schema discriminator.                                                                                     |
| `version`              | integer | always              | Schema version.                                                                                           |
| `pid`                  | integer | always              | Operating-system process id (PID) of the serving daemon. See the [PID-reuse caveat](#staleness-contract). |
| `port`                 | integer | always              | TCP port the daemon serves on.                                                                            |
| `started_at`           | string  | always              | ISO-8601 timestamp of the first publication.                                                              |
| `last_heartbeat`       | string  | always              | ISO-8601 timestamp of the most recent heartbeat.                                                          |
| `heartbeat_interval_s` | integer | always              | Seconds between heartbeats.                                                                               |
| `stale_after_s`        | integer | always              | Seconds after which a consumer treats the record as stale.                                                |
| `service_token`        | string  | always              | Bearer token for the daemon's token-gated HTTP routes.                                                    |
| `package_version`      | string  | always              | Release of the daemon that wrote the record.                                                              |
| `python_version`       | string  | always              | Python running the daemon.                                                                                |
| `phase`                | string  | always              | Lifecycle phase, for example `running` or `warming`.                                                      |
| `qdrant_pid`           | integer | managed server only | PID of the managed Qdrant process.                                                                        |
| `qdrant_alive`         | boolean | managed server only | Whether the daemon last observed that process alive.                                                      |
| `qdrant_port`          | integer | managed server only | Port the managed Qdrant serves on.                                                                        |
| `qdrant_version`       | string  | managed server only | Version of the managed Qdrant binary.                                                                     |
| `qdrant_start_time`    | float   | managed server only | Epoch seconds when the managed Qdrant started.                                                            |
| `qdrant_identity`      | object  | managed server only | The witnessed child's `pid`, `port`, and `start_time`.                                                    |

The `qdrant_*` fields are absent in local-only mode and when pointed at a remote Qdrant. Treat absent and null alike.

Parse `started_at` and `last_heartbeat` as ISO-8601 strings. Note that `qdrant_start_time` is epoch seconds, not ISO-8601.

A complete record, with the token redacted:

```json
{
  "schema": "vaultspec.rag.service",
  "version": 1,
  "pid": 46220,
  "port": 8766,
  "started_at": "2026-09-02T13:14:29+00:00",
  "last_heartbeat": "2026-09-02T14:51:04+00:00",
  "heartbeat_interval_s": 15,
  "stale_after_s": 60,
  "service_token": "<redacted>",
  "package_version": "0.4.21",
  "python_version": "3.13.14",
  "phase": "running",
  "qdrant_pid": 44568,
  "qdrant_alive": true,
  "qdrant_port": 8765,
  "qdrant_version": "1.19.0",
  "qdrant_start_time": 1788354870.6777313,
  "qdrant_identity": { "pid": 44568, "port": 8765, "start_time": 1788354870.6777313 }
}
```

## Typed resolution: ready, absent, degraded

Discovery is more than a port check. Resolution returns one typed, evidence-carrying verdict whose state is exactly one of three values.

- `ready`: a live lock holder has published a schema-valid, fresh pointer whose PID matches the holder. `port` carries a usable address.
- `absent`: no machine lock is held, so nothing is running. Only in this case does a consumer consult the status-file legacy fallback.
- `degraded`: a live holder owns the singleton, but its published pointer cannot be trusted.

`degraded` is deliberately distinct from `absent`, because something owns the singleton. On a `degraded` verdict a consumer must not:

- render the daemon as stopped
- fall back to a status-file address the owner never published
- start a second daemon, which would only lose the race

A `degraded` verdict carries a `reason` naming the specific disagreement:

| `reason`               | Meaning                                                                                 |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `pointer_missing`      | Live holder, but no pointer record.                                                     |
| `pointer_invalid`      | Pointer present, but its port is unreadable or malformed.                               |
| `pointer_stale`        | Pointer's `last_heartbeat` is older than its staleness window.                          |
| `pointer_foreign`      | Pointer names a PID other than the live holder, a leftover from a previous incarnation. |
| `probe_failed`         | The machine lock or pointer could not be inspected at all.                              |
| `pointer_incompatible` | Pointer declares a `schema` or `version` pair this build does not implement.            |

The verdict also preserves `holder_pid`, `pointer_pid`, `port`, `service_token`, `heartbeat_age_s`, and `stale_after_s` as evidence. Its `source` records which view supplied the address: `machine_pointer`, `status_file`, or `none`. A `status_file`-sourced `ready` verdict is a labeled legacy compatibility result, valid only because no live holder exists.

## Staleness contract

The daemon rewrites `last_heartbeat` every `heartbeat_interval_s` seconds. Treat the daemon as stale, and not live, when `now - last_heartbeat > stale_after_s`.

Read both thresholds from the record rather than hard-coding them. If the payload predates `stale_after_s`, fall back to a 60-second window.

**PID-reuse caveat.** After a crash without clean shutdown, a recorded `pid` may belong to an unrelated process. Don't treat a live `pid` alone as proof the daemon is up. Combine it with a fresh `last_heartbeat`. Where you need stronger proof, verify the `service_token` against the target port's `/health` response.

## Authority: the machine lock

The single authority for "a daemon is running on this machine" is an operating-system advisory lock, held on a lock file for the lifetime of the serving process. The operating system releases it automatically when the holder dies, so a crashed daemon never strands the lock, and no stale-file reclaim heuristic exists.

A discovery record is *evidence* of an address. The live lock is *proof* of ownership. When the two disagree, the lock wins.

The lock file, `service.lock`, lives beside the machine-global managed Qdrant storage rather than under the per-instance status directory, so it stays machine-wide even when the status directory is overridden.

## The two discovery views

The daemon publishes the same versioned payload to two files, both named `service.json`, in two directories. They serve different consumers.

| View            | Location                    | Authoritative                          | Purpose                                                                                                                       |
| --------------- | --------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Machine pointer | Beside the lock file        | Yes, mutated only by the lock owner    | The canonical address record. A consumer that doesn't share the daemon's status directory still finds the one running daemon. |
| Status file     | `{status_dir}/service.json` | No, an operator and compatibility view | Operator detail, and a legacy fallback for daemons predating the pointer.                                                     |

The [configuration reference](configuration.md) covers how `status_dir` resolves.

Deleting or corrupting the status file never stops the daemon from republishing canonical discovery: each heartbeat rebuilds a complete daemon-owned snapshot and recreates a missing or invalid status file.

## Ownership and authenticated publication

The machine pointer is owner-authenticated. A caller may publish or delete it only while it can present the process-local lease returned by a successful lock acquisition. The publish primitive verifies that the current process still holds that exact retained lease, and that the payload names the lease-owning PID. A PID read or a lock probe alone is not sufficient authorization. So a non-holder cannot overwrite or remove canonical discovery even if it reproduces the owner PID.

Publication is atomic. The writer creates a unique temporary file in the destination directory and replaces it into place, so a consumer never observes a partial document.

Parse both files structurally, not by layout. Their on-disk formatting differs: the machine pointer is pretty-printed, while the status-file writer emits compact JSON.

Startup writers to the status file serialize through an operating-system-backed lock, so either the launching CLI or the daemon may publish first, and the later writer merges rather than erasing fields the other already published. The daemon's same-port lifecycle publication is authoritative. On Windows a virtual-environment launcher's PID may differ from the serving daemon's, so once the daemon has stamped `phase`, a delayed parent write preserves the daemon PID, the first `started_at`, and the managed-Qdrant identity.

## Operator status

Every adapter renders one canonical operator verdict, composed from the typed resolution plus already-probed liveness signals. The verdict is derived once and rendered per surface, never recomputed.

| Operator state       | Meaning                                                                                  | Exit code |
| -------------------- | ---------------------------------------------------------------------------------------- | --------- |
| `running`            | Serving normally.                                                                        | 0         |
| `warming`            | Holds the singleton, loading models, not yet serving.                                    | 5         |
| `stopped`            | Nothing is running (resolution `absent`).                                                | 3         |
| `crashed`            | A recorded daemon is not serving: dead PID, reused PID, silent port, or stale heartbeat. | 4         |
| `degraded_discovery` | Live holder, untrustworthy pointer (resolution `degraded`).                              | 4         |

`degraded_discovery` reuses exit code 4, so a supervising broker needs no new code. The structured status body carries a `discovery` block with the resolution's state, source, both PIDs, port, heartbeat age, staleness window, reason, and a one-line `evidence` string.

Operations that depend on the daemon fail fast on a degraded resolution rather than guessing an address. Read-only status returns the complete observation.

For the operator-facing commands that render these states, see the [service mode guide](service-mode.md) and the [CLI reference](cli.md).

## Reconcile

A consumer cannot repair a degraded machine: the singleton owner is the only writer of canonical discovery. `vaultspec-rag server reconcile` waits for the owner to republish. It is non-destructive and idempotent, and it never stops, restarts, or terminates a process.

It re-resolves on an interval until its timeout. It succeeds only when the serving daemon's identity agrees across every axis the pointer claims: holder PID, pointer PID, freshness, port, service token, and the live `/health` response. It exits 0 once discovery agrees and 1 if it does not converge in time.

A wedged owner stays degraded, and the operator sees that state rather than a guessed recovery. For the command's flags, see the [CLI reference](cli.md).

## Where to go next

- [Architecture](architecture.md) answers what the daemon does and why it is a singleton.
- [Service mode](service-mode.md) answers how to start, observe, and stop the daemon.
- [Configuration](configuration.md) answers how the status directory and ports resolve.
- [MCP integration](mcp.md) answers how the MCP server reaches the daemon.
- [CLI reference](cli.md) catalogues every command, flag, and exit code.
- [Glossary](glossary.md) defines the vocabulary used here.

If you find a wedged owner that never recovers, or a record this contract does not describe, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports.
