---
tags:
  - '#exec'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:64885f4788a898b28b5f58e54bdcafc75cd023ddd21b0a8518a970634b4a7b3e'
related:
  - "[[2026-09-23-vault-result-evidence-plan]]"
---

# `vault-result-evidence` ledger

## Changes

- `S04` `A` `src/vaultspec_rag/_markdown_passages.py`
- `S04` `A` `src/vaultspec_rag/tests/test_markdown_passages.py`
- `S04` `verify:` `fence guard mutation (fence detection disabled) fails on the section equality, restored passes` -> `pass`
- `S03` `M` `src/vaultspec_rag/embeddings.py`
- `S03` `M` `src/vaultspec_rag/service.py`
- `S03` `M` `src/vaultspec_rag/search/_searcher.py`
- `S03` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S03` `M` `.vault/research/2026-09-23-vault-result-evidence-research.md`
- `S03` `M` `.vault/adr/2026-09-23-vault-result-evidence-adr.md`
- `S03` `verify:` `service vault search median rerank 1.089s->0.367s, total 1.140s->0.43s` -> `pass`

## Notes

- `S03` research and ADR speedup figure corrected from the scratch 6.6x to the in-service ~3x; the decision is unchanged
