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

LOCAL-002 | LOW | Watcher graph invalidation retained a legacy private-field fallback

The watcher accepted both `graph_cache` and a legacy `searcher` parameter, then fell back to mutating `searcher._graph_built_at`. This contradicted the current service graph contract and the clean-code constraint. Fixed by making `graph_cache.invalidate()` the only watcher invalidation path, removing the `searcher` parameter, and updating the regression test to reject the old private searcher path.

LOCAL-003 | LOW | Search concurrency contract follow-up review found no blocking issues

Reviewed the concurrency-contract documentation and the runtime surfaces added in `capabilities.py`, `mcp_server.py`, `cli.py`, `store.py`, and the focused tests. The contract now consistently states that concurrent search is accepted, same-project local Qdrant access serializes inside one process, cross-project slots can proceed independently, and local storage remains exclusive across processes. Focused ruff, mdformat, targeted MCP/CLI tests, and the unit marker passed.

LOCAL-004 | MEDIUM | GitHub Actions workflows still used Node 20 action majors

The successful 0.2.7 publish run emitted GitHub Actions warnings that `actions/checkout@v4`, `actions/upload-artifact@v4`, and `actions/download-artifact@v4` run on Node 20 and will be forced forward by GitHub in 2026. Fixed by updating workflow references to current Node-24-ready release tags: `actions/checkout@v6.0.2`, `actions/upload-artifact@v7.0.1`, and `actions/download-artifact@v8.0.1`. Verified the current action releases through the GitHub API and ran `actionlint`.
