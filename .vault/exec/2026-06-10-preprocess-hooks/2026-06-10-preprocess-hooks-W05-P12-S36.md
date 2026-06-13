---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S36'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add an end-to-end integration test: a command preprocessor fixture indexed on real GPU and Qdrant and searchable with anchors (D6, D12)

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

Added `tests/integration/test_preprocess_integration.py` with a `preproc_project` fixture
(real `EmbeddingModel`, real Qdrant, a real command extractor script, a `.vaultragpreprocess.toml`,
and a binary `report.pdf`). The end-to-end test full-indexes, then `VaultSearcher.search_codebase`
finds the extracted unit with `preprocessor_id`, a `#page=` anchor, a `page N` locator, and
`source_path` (D6, D12).

## Outcome

Passes on real GPU + Qdrant + subprocess (3 tests, ~24s warm). Per-test timeout raised to
600s because a cold session pays two model loads plus the CrossEncoder load.

## Notes

No mocks; the extractor is a real Python subprocess emitting schema-valid JSON.
