---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S28'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# report model presence by checking the HuggingFace cache for the configured dense, sparse, and reranker repos

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Report model presence by probing the Hugging Face cache for the configured dense, sparse, and reranker repos with `try_to_load_from_cache` - the same idempotency probe the warmup verb and the model provisioning step use - so the dimension neither downloads nor loads a model.
- Mark the dimension `ready` only when every configured repo is present; otherwise `not_ready` naming the missing repos with a provisioning remediation. When `huggingface_hub` is not importable, report `unknown` rather than misreporting absence as a broken dependency.
- Carry the per-repo presence map as structured `info` keyed by repo id.

## Outcome

- The models dimension reports `ready` on the dev host where all three configured repos are cached, and a presence map is surfaced in `info["repos"]` with boolean values. No network call is made.

## Notes

- Implemented in `src/vaultspec_rag/_readiness.py` (`_models_readiness`), not directly in `api.py`; see S26 notes.
