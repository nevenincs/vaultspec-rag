---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S15'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a model-ensure provisioning step that reuses the warmup snapshot-download path and reports cached versus downloaded idempotently

## Scope

- `src/vaultspec_rag/commands/_provision.py`

## Description

- Add `provision_models` reusing the warmup snapshot-download path: probe the HuggingFace cache per configured repo (dense, sparse, reranker) with `try_to_load_from_cache`, exactly as the `server warmup` verb does.
- Download only the absent repos via `snapshot_download`; a fully-cached set is an `unchanged` no-op with no network, a download is `created`.
- Honour `dry_run` (preview the missing repos), the `models` skip token, and a missing `huggingface_hub` import (skipped with reason); a per-repo download failure is reported, not swallowed.

## Outcome

The model-ensure step ensures the configured embedding/reranker models are present and reports `cached`-versus-`downloaded` idempotently through the shared vocabulary. No GPU or model load happens - only snapshot files are fetched, exactly like warmup's download loop, keeping the step safe to run inside a front door that must not touch the single GPU.

## Notes

The plan's scope row named `commands/_models.py` for this Step. It was instead hosted in `commands/_provision.py` (recorded in the Scope above) to keep the whole P04 contribution inside the module this executor exclusively owns and to avoid a cross-agent write collision: a concurrent process in the shared worktree was reverting unstaged edits to `_models.py`, which W02.P06 (S22) also targets. The public surface is unchanged - `provision_models` is exported from the commands package regardless of its host module.
