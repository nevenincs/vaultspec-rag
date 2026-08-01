---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:7c12f8fa0b1629b8b5abe75a9ccbc862fc0fb75d94db0b9af3e01f21ed3013b3'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# `index-cuda-ceiling` `P01` summary

All three Steps (`S01`-`S03`) complete. Documents encode on their own
sub-batch, decoupled from the vault and code knobs.

- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/indexer/_document_indexer.py`
- Modified: `src/vaultspec_rag/tests/test_config.py`

## Description

`embedding_document_encode_batch_size` (default 12, own env override) now
drives both document encode call sites, sized for window-bounded document
fragments (~2.7x the vault chunk's token volume) instead of falling through
to the vault sub-batch of 32. This retires the restart-fragile runtime env
workaround that had lowered the shared knob for every domain. An
independence test binds the decoupling in both directions: the document
default differs from vault/code, and its override perturbs neither sibling
knob.
