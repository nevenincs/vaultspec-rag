# Service discovery file (`service.json`)

The resident background service writes a discovery file that sibling tools read to locate the
daemon and judge whether it is alive. This document is the **consumer-facing contract** for that
file. It covers the fields a consumer may rely on, their formats, the version discriminator, and
the staleness semantics. Fields not listed under [Interface fields](#interface-fields) are
internal diagnostics and must not be relied upon.

## Location

`{status_dir}/service.json`, where `status_dir` is the CLI `--status-dir` override, else the
`VAULTSPEC_RAG_STATUS_DIR` environment variable, else `~/.vaultspec-rag/`.

The file is written atomically (write-to-unique-`.tmp` + `os.replace`), so a reader never
observes a partially written file. Startup writers serialize through an OS-backed
`service.json.lock`: either the launching CLI or the daemon may publish first, and the later
writer merges rather than erasing fields already published by the other process.

The daemon's same-port lifecycle publication is authoritative. This matters on Windows, where
the PID returned for a virtual-environment launcher may differ from the PID of the serving
daemon. Once the daemon has published `phase`, a delayed parent write preserves the daemon PID,
the first `started_at`, and the managed-Qdrant identity.

## Version discriminator

Every file carries a schema discriminator. Pin on the pair and refuse a file you do not
understand:

| Field     | Type    | Value                   |
| --------- | ------- | ----------------------- |
| `schema`  | string  | `vaultspec.rag.service` |
| `version` | integer | `1`                     |

`version` is bumped only on a breaking shape change, and this document is updated in the same
change. Additive fields do not bump the version.

## Interface fields

| Field                  | Type            | Format / meaning                                                                                                                                                  |
| ---------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema`               | string          | Schema discriminator (see Version discriminator).                                                                                                                 |
| `version`              | integer         | Schema version (see Version discriminator).                                                                                                                       |
| `pid`                  | integer         | OS process id of the serving daemon. See the PID-reuse caveat in the Staleness contract section.                                                                  |
| `port`                 | integer         | TCP port the service listens on (loopback).                                                                                                                       |
| `started_at`           | string          | Service start time, **ISO-8601 with UTC offset, second precision** (e.g. `2026-06-24T10:23:52+00:00`).                                                            |
| `last_heartbeat`       | string          | Time of the last heartbeat write, **same format as `started_at`**. Drives the staleness check.                                                                    |
| `heartbeat_interval_s` | integer         | Seconds between heartbeat writes.                                                                                                                                 |
| `stale_after_s`        | integer         | Age in seconds past which `last_heartbeat` is considered stale.                                                                                                   |
| `service_token`        | string          | Per-process identity token; also echoed by the ungated `/health` route for identity verification.                                                                 |
| `phase`                | string          | Daemon lifecycle phase: `warming` before readiness or `running` after startup completes.                                                                          |
| `qdrant_pid`           | integer or null | PID of the witnessed managed Qdrant child. Attached mode republishes the PID from validated managed identity; null means no witnessed managed child is available. |
| `qdrant_alive`         | boolean or null | Whether the supervised Qdrant child is alive.                                                                                                                     |
| `qdrant_port`          | integer or null | Port of the supervised Qdrant child.                                                                                                                              |
| `qdrant_version`       | string          | Pinned managed-Qdrant version witnessed by the daemon.                                                                                                            |
| `qdrant_start_time`    | number          | OS creation time of the witnessed Qdrant child, in epoch seconds. It binds `qdrant_pid` to one process incarnation.                                               |
| `qdrant_identity`      | object          | Complete managed-child witness containing `pid`, `start_time`, `port`, `version`, and `storage_path`.                                                             |

The `qdrant_*` fields are present only in managed-server mode. In local-only mode, and when the
service targets a remote Qdrant URL, the daemon supervises no child, so the fields are absent
from the file rather than null. Treat absent and null alike: no managed Qdrant child to report.
Managed-child identity is published immediately after the child is ready and before model
warming begins. Publication failure aborts startup; it is never silently deferred until the
first heartbeat.

When the daemon attaches to an already-running managed Qdrant, it does not own
the child process handle. The validated identity sidecar remains authoritative
for `qdrant_pid`, `qdrant_start_time`, port, version, and storage. Startup
publication and every later heartbeat preserve that witnessed identity.

Both timestamp fields use one declared format, ISO-8601 with a UTC offset at second precision, and
a single shared helper emits them so they never diverge. The offset is always UTC (`+00:00`).
Parse them as ISO-8601 and do **not** assume an epoch number.

## Staleness contract

The daemon rewrites `last_heartbeat` every `heartbeat_interval_s` seconds (default 15). A
consumer should treat the service as **stale / not live** when
`now - last_heartbeat > stale_after_s` (default 60). Read those two thresholds from the file
rather than hard-coding them, since they are authoritative for the daemon that wrote them.

**PID-reuse caveat.** A recorded `pid` may, after a crash without clean shutdown, belong to an
unrelated process. Do not treat a live `pid` alone as proof the service is up. Combine it with a
fresh `last_heartbeat`. Where stronger proof is needed, verify the `service_token` against the
target port's `/health` response.

The same rule applies to `qdrant_pid`. Destructive cleanup must require a positive
`qdrant_start_time` and revalidate that witness, the Qdrant image, loopback listener, pinned
version, and managed storage before signalling. A legacy identity without the child start-time
witness remains readable but cannot authorize automatic reaping.

The recorded Qdrant owner is also fail-closed. If its PID is live but its
process-start witness cannot be read, startup classifies ownership as
unverified and refuses to attach, reap, or spawn. Ordinary orphan cleanup
revalidates immediately before signalling that the recorded owner incarnation
is dead or has been replaced.

## Internal fields (not interface)

The file also carries process-introspection fields used by the local status surface:
`parent_pid`, `executable`, `prefix`, `base_prefix`, `virtual_env`, and GPU/model diagnostics
such as `cuda` and `models_loaded`. These are diagnostics only. They are **not** part of the
discovery contract and may change or disappear without a version bump. Do not depend on them.
