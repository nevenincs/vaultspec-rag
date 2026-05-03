---
tags:
  - '#audit'
  - '#project-hardening'
date: '2026-05-03'
related: []
---

# `project-hardening` Code Review

GEMINI-001 | CRITICAL | Text model padding was moved to `processor_kwargs`

Gemini flagged that the dense text embedding model should receive left-padding through `tokenizer_kwargs`, not `processor_kwargs`. The reviewed code could ignore the padding setting for text-only SentenceTransformer models or fail when no processor configuration exists. Fixed by restoring `tokenizer_kwargs={"padding_side": "left"}` on the dense `SentenceTransformer` load and adding regression coverage that rejects `processor_kwargs` for that call.

GEMINI-002 | MEDIUM | Sparse model loading forced non-safetensors weights

Gemini flagged that `use_safetensors=False` weakens the default model-loading path and can fail for repositories that only publish safetensors weights. Fixed by removing the explicit `use_safetensors` override from the sparse `SparseEncoder` load while keeping `DISABLE_SAFETENSORS_CONVERSION=1` as the warning-control mechanism. Added regression coverage that rejects `use_safetensors` in sparse model kwargs.

LOCAL-001 | LOW | Targeted post-fix review found no additional blocking issues

Reviewed the modified `EmbeddingModel.__init__` path and new regression tests after the Gemini fixes. The constructor arguments now preserve Qwen text-tokenizer behavior, avoid forcing pickle weights, and keep the prior warning suppression mechanism. Targeted lint, type checking, whitespace checks, and regression tests passed.
