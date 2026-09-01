---
tags:
  - '#reference'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:2480a363c8c53c2fd090d249f42dd0946aafba778eee791789fcc6c3c2e2f673'
related: []
---

# `generation-accounting` reference: `generation accounting repair blueprint`

The recovered branch changes generation ownership, finalization, and service-client
configuration. This blueprint locates the authoritative code paths and test seams for
the repair.

## Summary

`CodeGenerationLifecycle` creates a clean build collection while retaining the served
collection until publication. `CodeConsumerPipeline` writes slices to that build target,
but drift and stale cleanup currently omit their collection argument and therefore act on
the served collection. Threading the lifecycle-derived build target into those cleanup
operations preserves the publication boundary.

The ledger permits a converged rejection only when storage evidence and file state agree.
A resumed path that was previously upserted cannot be converted directly to skipped or
vanished: its stored points must be deleted from the active target and recorded as a
storage-confirmed deletion before its state can leave the manifest. The existing
delete-first, ledger-second incremental replacement path is the implementation analogue.

`resolve_timeout` is the canonical dynamic settings resolver used by administrative and
search calls. Reindex must use a matching resolver at request time rather than the
import-time default so the supported environment value affects live calls.

Key locators: `src/vaultspec_rag/indexer/_generation_lifecycle.py:170-198`,
`src/vaultspec_rag/indexer/_generation_lifecycle.py:297-383`,
`src/vaultspec_rag/indexer/_consumer_pipeline.py:411-492`,
`src/vaultspec_rag/indexer/_consumer_pipeline.py:674-702`,
`src/vaultspec_rag/indexer/_drift_owner.py:262-282`,
`src/vaultspec_rag/indexer/_run_ledger_files.py:164-214`,
`src/vaultspec_rag/indexer/_run_ledger_finalization.py:114-140`, and
`src/vaultspec_rag/serviceclient/_transport.py:402-439`.
