---
tags:
  - '#exec'
  - '#service-graph'
date: 2026-04-02
modified: '2026-06-30'
related:
  - '[[2026-04-02-service-graph-phase1-plan]]'
---

# service-graph phase-5 step-1: model prefetch (warmup command)

## Summary

Implemented `service warmup` CLI command (ADR decision D4) that
pre-downloads all three GPU model repositories to the local HuggingFace
cache without loading them onto the GPU.

## Files modified

- `src/vaultspec_rag/cli.py` -- added `service_warmup()` command to
  `service_app`. Checks CUDA via torch, resolves model repo IDs from
  config (`embedding_model`, `sparse_model`, `reranker_model`), checks
  HF cache via `try_to_load_from_cache`, downloads uncached models via
  `snapshot_download`, reports per-model status (cached / downloaded /
  failed) in a Rich table.

## Tests

- `src/vaultspec_rag/tests/test_cli_warmup.py` -- 4 unit tests verifying
  CUDA check, cached model reporting, repo ID display, and absence of
  failure status.

## Implementation details

- Sets `HF_HUB_DOWNLOAD_TIMEOUT=60` default via `os.environ.setdefault`
- Checks cache before attempting download to skip network calls for
  already-cached models
- Three status values: `cached`, `downloaded`, `failed` (with error)
- `huggingface_hub` import guarded with `ImportError` handler

## Test results

- 38 CLI tests pass (34 in test_cli.py + 4 in test_cli_warmup.py)
- ruff check and ruff format clean
- ty type checker clean
