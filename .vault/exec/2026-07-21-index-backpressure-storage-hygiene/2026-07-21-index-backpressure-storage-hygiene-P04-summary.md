---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---




# `index-backpressure-storage-hygiene` `P04` summary


## Description

Namespace hygiene. Alias normalization verified as shipped upstream;
`last_indexed` activity clock now stamped at every index-run completion
via `VaultStore.touch_manifest_last_indexed`; ephemeral idle-TTL reclaim
tier added to the policy engine (live + temp-rooted + expired persisted
clock, through the unchanged destruction gates, orphans first under the
shared cap, knob-gated, 0 disables).

- Modified: `src/vaultspec_rag/config.py`, `src/vaultspec_rag/store.py`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py`,
  `src/vaultspec_rag/indexer/_vault_indexer.py`,
  `src/vaultspec_rag/storage_ops.py`,
  `src/vaultspec_rag/server/_lifecycle.py`,
  `src/vaultspec_rag/tests/test_storage_ops.py`

Verification: storage/manifest/survey/ADR-regression/indexer suites green
(192).
