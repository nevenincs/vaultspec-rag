---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# add embedding_document_encode_batch_size to config defaults and the env-var mapping with a window-appropriate default

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Added the `EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE` env-var enum member.
- Mapped `embedding_document_encode_batch_size` in the env-override map.
- Added the default `12` with a comment justifying it from the window-sized
  fragment volume (~2.7x the vault chunk).

## Outcome

`config.embedding_document_encode_batch_size` resolves to `12` and honours its
own env override, verified by import. No property accessor was needed: the config
wrapper's `__getattr__` resolves any `_RAG_DEFAULTS` key through the base -> env
-> default order.

## Notes

The default `12` is set from live evidence - a batch of 8 cleared the failing
corpus with headroom on 2026-07-24, and 12 balances that against throughput. It
is a starting value, not a measured optimum.
