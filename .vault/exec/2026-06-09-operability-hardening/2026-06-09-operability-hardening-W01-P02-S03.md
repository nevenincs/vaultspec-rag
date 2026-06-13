---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'W01.P02.S03'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# `operability-hardening` W01.P02.S03 - gated-model fail-fast with remediation

scope: `src/vaultspec_rag/embeddings.py`

## Description

Wrapped dense (`SentenceTransformer`) and sparse (`SparseEncoder`) model construction in
`EmbeddingModel` so that `huggingface_hub.errors.GatedRepoError` and
`RepositoryNotFoundError` are caught and re-raised (`raise ... from exc`) as a `RuntimeError`
carrying actionable remediation: the model id, that it is gated/inaccessible, to set
`HF_TOKEN` or run `huggingface-cli login`, and the model URL. A small `_raise_for_hf_access`
helper maps the HF error and is reused for both models. No other exceptions are caught; no
CPU/sparse-only degradation is attempted (the stack is GPU-only by design). Lazy-import
discipline preserved.

## Outcome

Gated/inaccessible models now fail fast with a clear remediation message instead of an
opaque 401 traceback that kills daemon startup silently (#176). Confirmed import path
`from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError`
(`GatedRepoError` ⊂ `RepositoryNotFoundError` ⊂ `HfHubHTTPError`).

## Notes

Added 10 `unit` tests building real `GatedRepoError`/`RepositoryNotFoundError` instances
(real exception values, not mocks) and asserting the wrapped `RuntimeError` contains the
model id, `HF_TOKEN`, the URL, and the `__cause__` chain. `ruff`/`ty` clean.
