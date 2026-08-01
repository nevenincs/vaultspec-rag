---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:6548cdf84cb0195211345707e6a745577d6988807494be5d7cd835cdd9faf575'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# `index-drift-hardening` `P01` summary

All four Steps closed (S01-S04). Files touched across the Phase:

- Created: `src/vaultspec_rag/indexer/_config_epoch.py`
- Created: `src/vaultspec_rag/tests/test_config_epoch.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

Delivered the two-tier per-root config-epoch drift sentinel (ADR D1-D3). A
stdlib-only epoch module hashes membership inputs (sorted gitignore patterns,
vaultragignore file patterns, preprocess rule patterns) and content inputs
(preprocess invocation fields plus `html_strip`; `vault_chunk_chars` for the
vault tier). The codebase indexer resolves ignore specs and preprocess config
once per run through a shared scan-inputs bundle - a single gitignore tree walk
serves both the scan and the epoch - and classifies drift at every incremental
entry: content mismatch escalates to a clean rebuild, membership mismatch or a
legacy sidecar forces the unscoped incremental whose set arithmetic prunes
newly-ignored and admits newly-un-ignored files. Both epochs are stamped by the
meta writer on every successful index. The vault indexer mirrors the content
epoch over its chunking knob beside the existing layout sentinel, stamp-only on
legacy sidecars so upgrades never force a rebuild.

Verification: 22 new unit tests cover the escalation matrix over real tmp
roots, including a spy-based proof that the scoped path performs no extra tree
walk; 128 unit tests pass across the epoch and indexer modules; 37 GPU
integration tests (targeted-reindex, vault-chunking, codebase, gpu-pipeline)
pass with no spurious rebuilds; ruff and basedpyright report zero findings on
all four files. The orchestrator independently re-reviewed the escalation
dispatch and the meta-writer stamping before acceptance.
