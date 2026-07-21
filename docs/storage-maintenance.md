# Storage and maintenance

vaultspec-rag keeps semantic search indexes so agents and operators can search your projects by meaning instead of by exact keyword. In server mode, the default, one background service per machine owns a single managed vector store, and every project you index - each one a *root* - lives inside that one store. This guide covers how to inspect what that store holds, how the service reclaims dead data on its own, how to restore an index from an archive, how to prune space by hand, and how to watch maintenance as it runs.

Everything here needs the background service running. Start it with `uv run vaultspec-rag server start`. If you haven't set the service up yet, work through [getting started](getting-started.md) first, then [run the background service](service-mode.md) for the full startup and configuration walkthrough.

One caveat on scope: this all applies to the shared server-mode store. A `--local-only` store is private to a single project and carries none of this machinery, so the commands here don't apply to it.

## Vocabulary

| Term              | Meaning                                                                                                                                             |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| root              | A project directory that has been indexed.                                                                                                          |
| collection prefix | `r` + 12 hex characters + `_`, derived from a one-way hash of the resolved root path. It cannot be reversed to the path.                            |
| namespace         | All collections in the store sharing one root's prefix (typically a vault collection and a codebase collection).                                    |
| live              | The namespace's recorded root directory exists.                                                                                                     |
| orphaned          | The recorded root is gone, and its drive or share is reachable - a true deletion.                                                                   |
| unknown           | The store holds the namespace, but no root can be attributed to it. Never touched automatically.                                                    |
| unverifiable      | The root's volume or network share is offline, so existence cannot be checked. Never touched automatically.                                         |
| dangling data     | Namespaces whose source root no longer exists. They occupy disk but can never serve a useful search.                                                |
| grace window      | The continuous time a root must stay orphaned before automatic reclamation may act. The clock survives restarts and resets when the root reappears. |
| maintenance cycle | One scheduled pass of the service's storage maintenance: classify, advance grace clocks, reclaim, sweep archives, report.                           |
| snapshot archive  | A recoverable copy of a data-bearing namespace's collections, written immediately before automatic reclamation drops them.                          |

## Why disk usage grows

Creating a namespace preallocates a large block of storage immediately, before a single document is indexed. Every root you have ever indexed - including throwaway ones like test directories, temporary worktrees, and scratch checkouts - keeps costing that space until it is reclaimed. One development machine accumulated 79 dead namespaces totalling 167.9 GB, all holding zero documents.

That preallocation is why disk usage tracks the *number* of roots you have indexed far more closely than the amount of code and documents in them. It also means there are two different ways to get space back: removing namespaces you no longer need, and shrinking the ones you are keeping. Both are covered below, and the service does both on its own.

The store lives at `~/.vaultspec-rag/qdrant-server/storage` by default; `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` relocates it. Any location works, including deeply nested ones - on Windows the service hands the storage engine extended-length paths, so the classic 260-character path limit does not constrain where the store lives.

## Inspect what is stored

List every namespace with its classification, document count, footprint, and attributed root:

```
uv run vaultspec-rag server storage survey
```

```
144 namespaces  (orphaned=79 unknown=0 unverifiable=0 live=65)  300.8GB on disk
  orphaned r02c5d80096c3_         0 pts      2.1GB  C:\Users\me\AppData\Local\Temp\.tmpMum3wV
  live     r45b56789f389_     12408 pts      3.4GB  Y:\code\my-project
```

Each row reads left to right as the classification, the namespace prefix, the document count, the on-disk footprint, and the attributed root path; a namespace no root can be attributed to shows `(unattributable)` in the final column. `--orphaned` and `--unknown` narrow the list to those states. With a running daemon the survey is answered by the service itself, so the CLI, the MCP tools, and HTTP consumers all see one classification; without a daemon the CLI reads the store directly.

A running daemon answers from a cached survey snapshot rather than re-measuring every namespace per call, so the survey stays fast (sub-second) no matter how many namespaces the store holds. The snapshot is computed shortly after startup and refreshed by every maintenance cycle; the response carries `computed_at` (when the underlying survey ran) and `source` (`cache` or `fresh`) so a consumer can see exactly how old the data is. Survey data is therefore eventually-consistent, up to one maintenance interval behind. When you need up-to-the-second truth - for example immediately after indexing or deleting a namespace - pass `--fresh` (HTTP: `?fresh=true`), which recomputes the survey and reseeds the cache.

To look up a single root - which namespace and collection prefix belong to it - pass `--root`:

```
uv run vaultspec-rag server storage survey --root Y:\code\my-project
```

The output leads with `Queried root: <resolved path>  prefix: r..._`, and the same lookup is available as `queried_root` in `--json` output. This works even for a root that has never been indexed: the service computes the authoritative prefix, so an external consumer never has to reimplement the hash.

The full flag and exit-code table is in the [CLI reference](cli.md#server-storage-survey).

## Automatic reclamation

The running service reclaims confirmed-dangling namespaces on its own: a maintenance cycle runs every 60 minutes by default, with the first cycle one interval after startup. Set `VAULTSPEC_RAG_STORAGE_AUTOPRUNE=0` to disable it.

A namespace is only ever reclaimed automatically when all of the following hold:

- it is attributed to a known root,
- that root is classified `orphaned` - gone, on a reachable volume,
- and it has been orphaned continuously for its full grace window. The clock is persisted, so restarting the service does not reset it; the root reappearing resets it to zero instantly.

Reclamation is tiered. A namespace holding zero documents is dropped after 24 hours of continuous orphan-hood. A namespace holding data waits 7 days, then each of its collections is written to a snapshot archive, and the namespace is dropped only if every snapshot succeeded - a failed archive always cancels the drop.

The cycle never touches `unknown` namespaces, `unverifiable` namespaces (an unplugged drive looks exactly like a deleted root, so it is never treated as one), or - with one exception below - anything `live`. At most 16 namespaces are reclaimed per cycle; the remainder waits for the next one.

The exception is temp-rooted namespaces. A harness temp directory that still exists classifies `live` and would otherwise survive every prune forever, which is exactly how leaked harness namespaces once filled a disk. A namespace whose root lives under an OS temp directory therefore runs on an additional clock: every successful index run stamps a persisted `last_indexed` time, and once that stamp is older than the ephemeral idle TTL (72 hours by default) the namespace is treated as dangling even though its root exists. The same tiers then apply - empty ones drop, data-bearing ones are archived first - under the same per-cycle cap, with ordinary orphans taking priority. An actively re-indexed temp root keeps refreshing its stamp and is never touched; set `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS=0` to disable the tier.

The interval, both grace windows, the ephemeral idle TTL, the per-cycle cap, and the archive bounds are tunable - see the [storage maintenance knobs](configuration.md#storage-maintenance-auto-prune).

## Shrinking collections you keep

Reclamation removes namespaces you no longer need. Geometry reconcile is the other half: it shrinks the preallocation of namespaces you are keeping.

A collection's on-disk cost is dominated by a fixed floor rather than by its contents - the storage engine preallocates a set of memory-mapped pages per segment, and it sizes the segment count from the host's CPU count unless told otherwise. On a 24-core machine that meant eight segments and roughly 1.2 GB for a collection holding zero documents. Newer versions cap this at creation, but a collection carries the geometry it was created with for its whole life, so upgrading does not shrink anything that already exists.

The service converges them for you. Each maintenance cycle reconciles up to four drifted collections onto the bounded geometry, so a backend full of oversized collections shrinks over the following few hours without any action. Measured across collection sizes from empty to 20,000 documents, this reclaims 63-84% of each collection's footprint.

Reconcile is not destructive. It changes a setting and lets the storage engine merge segments in the background: no document is moved or deleted, and the collection stays searchable throughout. It is also idempotent - a collection already at the target is skipped, so once your backend has converged the stage does nothing.

To converge everything at once instead of waiting for the cycles, preview and then apply:

```
uv run vaultspec-rag server storage reconcile --dry-run
uv run vaultspec-rag server storage reconcile --yes
```

```
Reconciled 6 collections (23.4GB reclaimed); 0 still drifted.
  reconciled       r45b56789f389_vault_docs         8->1 segments, 1.0GB freed
```

Merging is a background operation, so the command waits for each collection to settle before reporting what it saved. That wait matters: while the engine restructures a collection, both its segment count and its on-disk size briefly rise *above* where they started before falling well below. A figure read mid-merge would report a reclamation in progress as growth, so `vaultspec-rag` only ever reports a size it has watched stop changing — and it waits for the merge to actually *begin* before it starts watching, because a merge still queued behind a busy engine looks exactly as motionless as a finished one.

Pass `--no-wait` to issue the changes and return immediately; the collections still converge on their own, but that run reports no reclaimed bytes, because at that moment there is no honest number to give. `--limit` bounds how many collections one run touches.

A merge needs room to inflate before it shrinks, so a collection is skipped with `insufficient_headroom` when the volume is too full to absorb it safely. If you hit that, prune first and reconcile afterwards.

Set `VAULTSPEC_RAG_STORAGE_RECONCILE=0` to disable the automatic stage; the per-cycle cap and the convergence budget are tunable alongside it.

One residue is left behind deliberately. The write-ahead log size is fixed when a collection is created and cannot be changed in place, so a reconciled collection keeps a 32 MiB log where a freshly created one takes 16 MiB. That is a small fraction of a floor measured in gigabytes, and removing it would mean recreating the collection - a far riskier operation for far less space.

## Archives and how to restore them

Snapshot archives land in `~/.vaultspec-rag/qdrant-server/archive/<prefix>/`, one subdirectory per reclaimed namespace and one `.snapshot` file per collection. Each maintenance cycle deletes archives older than 30 days, then evicts oldest-first if the archive directory exceeds 20 GB; both bounds are configurable.

The simplest restore is usually to reindex: the index is derived data, so if the root itself still exists (or came back from your own backup), indexing it rebuilds everything. To recover the archived index directly instead, use Qdrant's snapshot recovery against the managed server:

```python
from qdrant_client import QdrantClient

client = QdrantClient(url="http://127.0.0.1:8765")
client.recover_snapshot(
    collection_name="r0123456789ab_vault_docs",
    location="file:///C:/Users/me/.vaultspec-rag/qdrant-server/archive/r0123456789ab/r0123456789ab_vault_docs-....snapshot",
)
```

The snapshot path must be readable by the Qdrant server process, which it is on the machine that wrote it.

## Reclaim space manually

Manual pruning removes every orphaned namespace immediately - no grace window applies, because the operator running the command is the confirmation. Preview first, then apply:

```
uv run vaultspec-rag server storage prune --dry-run
uv run vaultspec-rag server storage prune --yes
```

```
Reclaimed 79 orphaned namespaces (167.9GB); 0 unknown left untouched.
```

Prune targets only `orphaned` namespaces; `unknown` and `unverifiable` are never touched. To remove one specific namespace, name its prefix:

```
uv run vaultspec-rag server storage delete r0123456789ab_ --yes
```

`delete` refuses a prefix the manifest cannot attribute to a root unless you pass `--allow-unknown`. The sensible order is survey, then prune, and delete only when you must remove one namespace the prune would not.

A crash can leave a half-written collection directory that the server cannot load (its config file never landed); the server skips it at startup and it would otherwise sit on disk forever. The survey lists such directories with status `debris`, and `prune --debris` removes them - a plain filesystem delete, since Qdrant cannot snapshot or drop a collection it never loaded. Debris removal is never automatic: it has no manifest attribution, so it stays behind the explicit flag plus the prune confirmation.

```
uv run vaultspec-rag server storage prune --debris --dry-run
uv run vaultspec-rag server storage prune --debris --yes
```

You can also address a namespace by its root path instead of its prefix - the sanctioned teardown for test harnesses and consumers that register throwaway roots against the resident service:

```
uv run vaultspec-rag server storage delete --root C:\Temp\my-throwaway-root --yes --json
```

The path is resolved and hashed exactly as indexing does, so it removes precisely the namespace that root's indexing created. Deletion is idempotent: an already-absent namespace reports `already_absent` and exits `0`, so a teardown hook can run unconditionally. A harness that instead simply deletes its temp roots is also fine - the automatic reclamation above removes the leftover namespaces once their grace window passes.

### Harnesses must isolate or tear down

A test, demo, or acceptance harness that indexes a throwaway root against the
resident service mints a real namespace in the shared backend - often gigabytes
once fully indexed - and as long as the temp directory still exists it
classifies `live` and survives every prune. Left alone, leaked harness
namespaces can exhaust the disk (the issue-242 incident: 36 temp-rooted
namespaces, ~74 GB). Every harness must do one of these, in order of
preference:

1. **Isolate**: point `VAULTSPEC_RAG_STATUS_DIR` and
   `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` at harness-owned temp paths so its
   indexing never reaches the shared backend at all.
1. **Tear down**: run `vaultspec-rag server storage delete --root <dir> --yes`
   unconditionally in the harness's cleanup (idempotent, exits `0` when
   already absent).
1. **Delete the root and wait**: removing the temp directory itself lets the
   scheduled reclamation collect the namespace after its grace window.

`server storage survey` marks suspect entries: any namespace whose root lives
under an OS temp directory is flagged `temp_rooted` in `--json` and `[temp]`
in the human table, so leaked harness indexes are visible before they become a
disk incident.

Flags and exit codes are in the [CLI reference](cli.md#server-storage-prune).

## Observe maintenance

Every cycle is a job: `uv run vaultspec-rag server jobs` lists it as a `storage maintenance cycle` with a result summary like `removed=2 failed=0 pending=5 reclaimed_bytes=4508876800`. Every cycle also writes one structured `service.maintenance` log line with the same counts plus archive activity and free disk, and logs an explicit `disk_low` warning when the store's volume drops under 10 GB free - only a few namespaces of headroom, so treat the warning as a prompt to prune or add capacity.

The token-gated `/metrics` route exports the rollup in Prometheus text format. All names carry the `vaultspec_rag_` prefix:

| Metric                               | Type    | Meaning                                                 |
| ------------------------------------ | ------- | ------------------------------------------------------- |
| `maintenance_cycles_total`           | counter | Cycles run since service start                          |
| `maintenance_reclaims_total`         | counter | Namespaces reclaimed since service start                |
| `maintenance_disk_free_bytes`        | gauge   | Free disk on the store's volume at the last cycle       |
| `maintenance_dangling_bytes`         | gauge   | Total footprint of currently orphaned namespaces        |
| `maintenance_pending_grace`          | gauge   | Orphans still inside their grace window                 |
| `maintenance_orphaned_namespaces`    | gauge   | Orphaned namespace count at the last cycle              |
| `maintenance_last_reclaimed_bytes`   | gauge   | Bytes reclaimed by the last cycle                       |
| `store_total_bytes`                  | gauge   | Whole-backend on-disk footprint (all statuses)          |
| `store_namespaces`                   | gauge   | Total namespace count at the last cycle                 |
| `maintenance_reconciled_total`       | counter | Collections shrunk onto the bounded geometry            |
| `maintenance_reconciled_bytes_total` | counter | Bytes reclaimed by geometry reconcile                   |
| `store_drifted_collections`          | gauge   | Collections not yet converged onto the bounded geometry |

`store_drifted_collections` counts both collections still carrying oversized geometry and collections whose setting is already correct but whose merge is still running - so it reaching zero genuinely means the backend has finished converging, not merely that the settings have been written. Note that `maintenance_reconciled_bytes_total` credits only merges a cycle watched to completion; a merge that outlives its convergence budget still finishes, but its bytes go uncounted.

The survey (`--json` and `GET /storage/survey`) carries the same rollup as a `totals` object: whole-backend bytes, namespace count, and a per-status byte breakdown - so a pile of live-but-leaked namespaces is visible even though it never counts as dangling.

Tuning the schedule, grace windows, cap, and archive bounds is covered by the [storage maintenance knobs](configuration.md#storage-maintenance-auto-prune).

## Where to go next

- [CLI reference](cli.md) - full flag and exit-code tables for `server storage survey`, `server storage prune`, `server storage delete`, and `server stop`.
- [Configuration](configuration.md) - every tunable, including the storage maintenance knobs.
- [Storage backends](backends.md) - the server-first backend model and the managed Qdrant server.
- [Run the background service](service-mode.md) - service lifecycle, status, jobs, and logs.
- Support: open an issue at [github.com/nevenincs/vaultspec-rag/issues](https://github.com/nevenincs/vaultspec-rag/issues).
