---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:665da3321d5e4d3b1f0503ef58281af3de4e91b790ce64ff822c12db28c7b0ff'
step_id: 'S12'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify real streaming and vault indexing observe control between slices without exposing partial rebuilds using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Exercise production vault streaming with real files, local Qdrant, the real
  run-control token, and a CPU-backed production embedding path.
- Request pause and cancellation only after a slice is observably published,
  then verify streaming unwinds before publishing the complete corpus.
- Hold the real GPU lock across a clean rebuild, request pause after the
  collection is dropped inside the protected span, and verify the request
  remains pending until replacement points and metadata are complete.
- Verify formatting, static types, focused integration behavior, adjacent
  control/indexer regressions, and architecture constraints through independent
  review.

## Outcome

Production streaming now has deterministic integration coverage proving pause
and cancellation delivery between real one-document slices. Clean rebuild
coverage observes the actual empty collection while publication protection is
active and proves all document IDs, revised stored content, and the revised
metadata hash are published before pause acknowledgement.

Ruff, Ruff formatting, ty, strict BasedPyright, and `git diff --check` passed.
All 3 focused integration cases, 17 adjacent run-control cases, and 106 indexer
unit cases passed. Independent review found no Critical or High issues.

## Notes

The first collection attempt used pytest's reserved `request` parameter name;
renaming it to `control_request` resolved collection before production behavior
ran. The test model is a real CPU `SentenceTransformer` BoW backend invoked
through `EmbeddingModel.encode_documents`; it avoids the recorded CUDA OOM and
does not use a fake, stub, patch, or mirrored implementation.
