---
tags:
  - '#research'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-25-archive-restore-contract-adr]]"
  - "[[2026-07-25-archive-restore-contract-plan]]"
  - "[[2026-07-25-archive-restore-contract-archive-path-reference]]"
---
# `archive-restore-contract` research: `Archive restore evidence`

## Findings

### Retained preamble

Archive creation currently authorises deletion but does not prove recoverability; the accepted contract and its plan therefore remain grounded in a real, still-open recovery gap rather than an undocumented preference.

### Archive creation does not establish restore readiness

`storage_ops.py:1564`, `storage_ops.py:1771`, and `storage_ops.py:1801` create snapshots, copy metadata, and write the manifest after the artifacts exist, but do not reread or recover a completed archive. The maintenance branch separately recounts points before deletion. The ADR records a write-time integrity check and a real-server round trip as the evidence still needed; `2026-07-25-archive-restore-contract-adr`.

### File-level retention can preserve incomplete archives

`storage_ops.py:1650` evicts archive files individually. Because the manifest follows snapshots and copied metadata retains its source timestamp, retention can keep a manifest after a named artifact has gone. The reference and plan identify archive-owned completion time and directory-level retention as the alternative under evaluation; `2026-07-25-archive-restore-contract-archive-path-reference` and `2026-07-25-archive-restore-contract-plan`.

### A client recovery primitive exists but has no product path

`qdrant-client@1.18.0` exposes synchronous `recover_snapshot` with a local `file:///` location in `qdrant_client/qdrant_client.py:2304`. Managed archive and storage roots are siblings in `server/_lifecycle.py:517`, yet no production use of `recover_snapshot` exists and `cli/_service_storage.py:63` exposes no restore operation. The current integration test verifies artifacts and manifest content but not recovery or a restored-data query; `tests/integration/test_document_store.py:293`.

## Sources

- `2026-07-25-archive-restore-contract-adr`
- `2026-07-25-archive-restore-contract-plan`
- `2026-07-25-archive-restore-contract-archive-path-reference`
- `src/vaultspec_rag/storage_ops.py:1564`
- `src/vaultspec_rag/storage_ops.py:1650`
- `src/vaultspec_rag/storage_ops.py:1771`
- `src/vaultspec_rag/server/_lifecycle.py:517`
- `src/vaultspec_rag/cli/_service_storage.py:63`
- `src/vaultspec_rag/tests/integration/test_document_store.py:293`
- `uv.lock:1383`
- `qdrant_client/qdrant_client.py:2304`
