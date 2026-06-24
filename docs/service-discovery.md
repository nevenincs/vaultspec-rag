# Service discovery file (`service.json`)

The resident background service writes a discovery file that sibling tools read to locate the
daemon and judge whether it is alive. This document is the **consumer-facing contract** for that
file: the fields a consumer may rely on, their formats, the version discriminator, and the
staleness semantics. Fields not listed under [Interface fields](#interface-fields) are internal
diagnostics and must not be relied upon.

## Location

`{status_dir}/service.json`, where `status_dir` is the CLI `--status-dir` override, else the
`VAULTSPEC_RAG_STATUS_DIR` environment variable, else `~/.vaultspec-rag/`.

The file is written atomically (write-to-`.tmp` + `os.replace`), so a reader never observes a
partially written file. It is written first by the launching CLI process and then merged on
every heartbeat tick by the daemon.

## Version discriminator

Every file carries a schema discriminator. Pin on the pair and refuse a file you do not
understand:

| Field | Type | Value |
| --- | --- | --- |
| `schema` | string | `vaultspec.rag.service` |
| `version` | integer | `1` |

`version` is bumped only on a breaking shape change, and this document is updated in the same
change. Additive fields do not bump the version.

## Interface fields

| Field | Type | Format / meaning |
| --- | --- | --- |
| `schema` | string | Schema discriminator (above). |
| `version` | integer | Schema version (above). |
| `pid` | integer | OS process id of the serving daemon. See the PID-reuse caveat below. |
| `port` | integer | TCP port the service listens on (loopback). |
| `started_at` | string | Service start time, **ISO-8601 with offset, second precision** (e.g. `2026-06-24T10:23:52+00:00`). |
| `last_heartbeat` | string | Time of the last heartbeat write, **same format as `started_at`**. Drives the staleness check. |
| `heartbeat_interval_s` | integer | Seconds between heartbeat writes. |
| `stale_after_s` | integer | Age in seconds past which `last_heartbeat` is considered stale. |
| `service_token` | string | Per-process identity token; also echoed by the ungated `/health` route for identity verification. |
| `qdrant_pid` | integer or null | PID of the supervised Qdrant child, when one is managed. |
| `qdrant_alive` | boolean or null | Whether the supervised Qdrant child is alive. |
| `qdrant_port` | integer or null | Port of the supervised Qdrant child. |

Both timestamp fields use one declared format — ISO-8601 with offset at second precision — and
are emitted by a single shared helper so they never diverge. Parse them as ISO-8601; do **not**
assume an epoch number.

## Staleness contract

The daemon rewrites `last_heartbeat` every `heartbeat_interval_s` seconds (default 15). A
consumer should treat the service as **stale / not live** when
`now - last_heartbeat > stale_after_s` (default 60). Read those two thresholds from the file
rather than hard-coding them, since they are authoritative for the daemon that wrote them.

**PID-reuse caveat.** A recorded `pid` may, after a crash without clean shutdown, belong to an
unrelated process. Do not treat a live `pid` alone as proof the service is up; combine it with a
fresh `last_heartbeat` and, where stronger proof is needed, verify the `service_token` against
the target port's `/health` response.

## Internal fields (not interface)

The file also carries process-introspection fields used by the local status surface:
`parent_pid`, `executable`, `prefix`, `base_prefix`, `virtual_env`, and GPU/model diagnostics
such as `cuda` and `models_loaded`. These are diagnostics only — they are **not** part of the
discovery contract and may change or disappear without a version bump. Do not depend on them.
