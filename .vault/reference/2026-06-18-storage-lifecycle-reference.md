---
tags:
  - '#reference'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# `storage-lifecycle` reference: `migrate fast-tooling spike`

Bounded research spike (the prescribed first step of the migrate wave) selecting
the fastest, ideally C-backed, Python approach to move a per-root Qdrant index
between backends (local on-disk and the managed server), verified live against
qdrant-client 1.18.0.

## Summary

### Built-in migrate helper (v1, correctness-first)

qdrant-client 1.18.0 ships `QdrantClient.migrate(dest_client, collection_names, batch_size=100, recreate_on_collision=False)`. Internally it reads the source
`get_collection().config`, recreates the target with the full schema (named
dense + sparse vectors, distance, HNSW/optimizer/WAL/quantization config, and
every payload index from `payload_schema`), then pages
`scroll(with_vectors=True)` into a retrying batched upload, finishing with a
source-vs-destination count assertion. It works between any two clients,
including local on-disk and server, because the local engine implements
`scroll`/`create_collection`/`upsert`. This removes the need to hand-roll schema
recreation.

### The naming gap (why v1 cannot be the bare built-in)

The built-in copies a collection under the same name. This project namespaces
server collections per root as `r{hash}_{base}` while local mode uses the bare
`vault_docs` / `codebase_docs`. A local-to-server migrate must therefore copy
`vault_docs` into `{prefix}vault_docs` (and the reverse) - a rename the built-in
does not perform (Qdrant has no rename; aliases do not move data). The v1
implementation reuses the built-in's approach (read source config, create target
with the mapped name, scroll + upload) with an explicit source-name to
target-name map.

### Fast-path optimization (deferred, for the speed bar)

Two independent levers, both available today and both genuinely C-backed:

- gRPC transport on the server client: `prefer_grpc=True` plus
  `grpc_options={"grpc.max_send_message_length": -1, "grpc.max_receive_message_length": -1}`. The gRPC stack is C-backed (cygrpc +
  upb protobuf) and avoids REST JSON-encoding of large float arrays - the
  dominant cost for multi-GB dense+sparse data. Only the server leg benefits;
  the local leg ignores transport.
- Parallel bulk upload: `upload_points(points, batch_size=256, parallel=4, method="spawn", wait=False)` for a server destination (`parallel=1` for a
  local destination). On Windows `parallel>1` must pass `method="spawn"` (the
  default `forkserver` does not exist), matching the project's existing
  spawn-only worker discipline.

numpy (already a dependency) only helps the all-dense `upload_collection` path;
pyarrow is irrelevant (Qdrant's wire format is protobuf/JSON, not Arrow).

### Snapshots: server-to-server only

`create_snapshot` / `recover_snapshot` are the fastest server-to-server path but
require the snapshot location to be reachable by the destination server, and
there is no high-level uploaded-snapshot helper in 1.18.0. Local mode raises
`NotImplementedError` for snapshots, so they are categorically unavailable for
the local-to-server case this project performs.

### Windows / local caveats

- Local-engine `scroll` is O(N^2) over pages (documented in `store.py`'s
  `_id_scan_page_limit`): when the source is local, read in few large pages and
  run off the hot service thread.
- gRPC needs the raised message-size limits above to clear the 4 MB default cap
  on large batches.
- Bound the read page size (256-512 with vectors attached) to cap peak memory.

### Decision

v1 ships a name-mapped scroll + schema-recreate + upload copy (correctness, works
local-to-server with the prefix rename, count-verified), holding the GPU lock
never (pure storage I/O) and reusing the single GPU consumer only if a future
variant re-embeds. The gRPC + parallel-upload fast path is a follow-up
optimization behind the same service function, not a v1 blocker.

Source: qdrant-client 1.18.0 (`qdrant_client/migrate/migrate.py`,
`qdrant_client/local/qdrant_local.py`); Qdrant migration and snapshots docs.
