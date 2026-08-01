---
tags:
  - '#reference'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:0513c35217d722e8544670766967399d629f0639baae0fae59b707655ec3d0b4'
related: []
---

# `archive-restore-contract` reference: `what the archive path writes, keeps, and offers a reader today`

Grounding read of the archive-and-destroy path as it stands, taken to decide
whether a restore ships and what it could be built on. Sources: `storage_ops.py`,
`storage_manifest.py`, `server/_lifecycle.py`, `cli/_service_storage.py`, the
storage test modules, and the pinned Qdrant client's own API surface.

## Summary

**F1 - `archive_prefix` is the only snapshot-creating code, and the only writer
into the archive tree.** It lives at `src/vaultspec_rag/storage_ops.py:1413`. For
each collection sharing the prefix it calls the client's `create_snapshot` with
`wait=True`, then `os.replace`s the resulting file out of the server's snapshots
tree into `archive_dir/{prefix without trailing underscore}/`. It raises on a
snapshot description without a name and on a snapshot file that is not where the
server said it would be. It copies the root's document-index metadata file
alongside when one exists, using `shutil.copy2`. It finishes by writing
`snapshot-manifest.json` and returning every path it produced, the manifest last.

**F2 - The snapshot manifest records enough to identify a namespace and not
enough to judge one.** `StorageSnapshotManifest` at
`src/vaultspec_rag/storage_manifest.py:141` carries the prefix, the source root
or `None`, the storage schema generation, one record per collection (exact name,
snapshot filename, point count), and the copied metadata filenames. It carries no
per-collection identity: the plan step that would add it is authored under the
storage-conformance feature and still open, so every archive written to date
records what a namespace was called and nothing about what produced its vectors.
It also carries no timestamp of its own.

**F3 - The caller refuses the drop on any archive failure.**
`run_maintenance_cycle` at `src/vaultspec_rag/storage_ops.py:1581` wraps the
`archive_prefix` call for a `reclaim_data` decision in a try/except and, on
failure, records the namespace as `failed` with an `archive_failed` reason and
skips `delete_prefix` entirely. The guard is real and is the only thing standing
between an unattended cycle and unarchived semantic data.

**F4 - Nothing reads an archive back.** `sweep_archive` at
`src/vaultspec_rag/storage_ops.py:1493` is the archive tree's only other
consumer and it only deletes. The pinned client's recovery calls appear nowhere
in the package. The `restore`-named symbols that do exist belong to the in-memory
job registry and are unrelated.

**F5 - The retention sweep operates on files, not on archives.** `sweep_archive`
walks `archive_dir.rglob("*")`, collects every file with its own modification
time and size, deletes those past the age cutoff individually, then evicts the
remainder oldest-first until under the byte cap. Two consequences follow
directly. The byte cap can remove a namespace's `.snapshot` files while leaving
its `snapshot-manifest.json`, which is written last and is therefore the newest
file in the directory - a manifest describing data that is gone. And because the
metadata file is copied with `copy2`, it carries the source file's modification
time, which is the last document-index time and can be far older than the
archive, so the age cutoff can expire it on a clock unrelated to the archive's
own age. Neither case is detected or reported.

**F6 - The archive tree is a sibling of the storage dir on the daemon host.**
`_maintenance_paths` at `src/vaultspec_rag/server/_lifecycle.py:515` derives
collections, snapshots, and archive directories from the configured Qdrant
storage dir: `storage/collections`, `storage.parent/snapshots`, and
`storage.parent/archive`. The supervised server runs on the same host and, per
`qdrant_runtime/_supervise.py`, has both the storage and snapshots directories in
its containment set.

**F7 - The pinned client can recover a collection from a location on the server
host.** `qdrant-client>=1.16.0` exposes
`recover_snapshot(collection_name, location, ..., wait=True)` alongside
`create_snapshot`, `list_snapshots`, and the shard-level equivalents. Because the
daemon and the Qdrant process share a host and the archive sits beside the
server's own snapshots tree (F6), the mechanism a restore needs already exists
and needs no new dependency.

**F8 - A namespace only reaches the archive path once its root has been
continuously absent.** `evaluate_reclaim` and `_decide_orphan` at
`src/vaultspec_rag/storage_ops.py:1296` and `:1348` consider only `orphaned`
survey entries; `live`, `unknown`, and `unverifiable` never appear in the output.
`classify_root` at `src/vaultspec_rag/storage_manifest.py:505` returns
`unverifiable` rather than `orphaned` whenever the root's own drive or share
anchor is unreachable, and `update_orphan_stamps` clears the grace stamp on any
non-orphaned observation, so the clock measures continuous absence and any
contrary observation restarts it.

**F9 - The empty tier already re-counts immediately before its drop; the data
tier does not.** In `run_maintenance_cycle`, a `reclaim_empty` decision calls
`_prefix_has_points` and defers the namespace when points appeared since the
survey. The `reclaim_data` branch has no equivalent re-read of what it just
wrote: it archives and proceeds.

**F10 - The prefix is a one-way hash of the resolved root path.**
`root_collection_prefix` in `src/vaultspec_rag/store.py` produces `r` plus a
12-hex blake2b digest plus `_`, and `_CANONICAL_PREFIX_RE` at
`src/vaultspec_rag/storage_ops.py:98` enforces exactly that shape as a hard gate
on every delete target, unrelaxed by `allow_unknown`. A namespace restored under
a different root therefore does not reuse the collection names its archive was
taken from, and the prefix cannot be reversed to a root without the manifest.

**F11 - The storage CLI verbs talk to the managed Qdrant server directly.**
`_run_storage_op` at `src/vaultspec_rag/cli/_service_storage.py:80` opens a
`QdrantClient` against the resolved server URL and runs the operation in-process,
mapping an unreachable server to exit 3 and a refused call to exit 1, and
guaranteeing a structured envelope on every `--json` exit path. The group already
holds survey, delete, prune, reconcile, and migrate; a restore verb would sit
beside them under the same helper.

**F12 - `migrate_collections` is the existing precedent for a copy that never
overwrites.** At `src/vaultspec_rag/storage_ops.py:1069` it skips a mapped
collection whose target already exists with a `target_exists` reason rather than
replacing it, verifies the destination count against the source, and reports
through the sync vocabulary. Its helper `_copy_collection` recreates the target's
vector schema from the source config and pages points across; payload indexes are
left to the store's ensure path on next open.

**F13 - The only test touching `archive_prefix` never opens the artifact.**
`src/vaultspec_rag/tests/integration/test_document_store.py:293` archives a real
namespace against a real supervised server and asserts on the manifest's JSON
contents and on file existence. `src/vaultspec_rag/tests/test_storage_ops.py`
states in its own module docstring that the server-backed archive functions are
covered at the integration level. No test reads a `.snapshot` back.

**F14 - The harness a round trip would need already exists.** The same
integration module provisions the pinned Qdrant binary, serves it on ephemeral
ports against temp storage, and points store construction at it via a fixture
that overrides the Qdrant URL and the status directory and resets config on the
way out. That fixture does not currently isolate the Qdrant storage-dir
environment variable, which a test writing the identity sidecar or taking the
machine lock would additionally need.

**F15 - Maintenance is regression-guarded as lifecycle-inert in one direction
only.** `src/vaultspec_rag/tests/test_adr_regression.py:447` asserts that the
maintenance import graph excludes the CLI lifecycle modules and that maintenance
sources never name the terminate helpers. There is no assertion in the reverse
direction - nothing today would stop a future edit reaching a new
collection-creating operation from the scheduled tick.
