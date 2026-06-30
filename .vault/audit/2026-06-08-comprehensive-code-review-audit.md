---
tags:
  - '#audit'
  - '#comprehensive-code-review'
date: '2026-06-08'
modified: '2026-06-30'
related:
  - '[[2026-06-01-module-split-adr]]'
---

# `comprehensive-code-review` Code Review

## Execution Paths & Latency-001 | HIGH | Unnecessary loop blocking in Qdrant scrolls

`src/vaultspec_rag/store.py` holds `self._client_lock` over the entire `while True:` pagination loop in `_scroll_all_ids` and `list_all_documents`. Since local Qdrant scrolling involves multiple sequential API requests, holding this global store lock blocks all concurrent search and upsert operations in the daemon process across all clients until the entire index is scrolled. The lock should only be held around the individual `self.client.scroll` calls, not the entire loop.

## Execution Paths & Latency-002 | MEDIUM | Hidden exception swallowing in graph builder

In `src/vaultspec_rag/search/_searcher.py`, the `_get_graph()` method catches a generic `Exception` when `_VaultGraph(self.root_dir)` fails, logs it, and returns `None`. While this correctly fails open to allow search to proceed without graph boosts, it silently swallows potential critical initialization or disk errors, hiding graph corruption or misconfiguration from operators. It should raise a typed exception or ensure metrics capture the failure so it can be surfaced.

## Sparse Fallback Boundaries-001 | HIGH | Indexer ignores `sparse_enabled` config

While `src/vaultspec_rag/search/_searcher.py` cleanly falls back to dense-only queries when `sparse_enabled` is False, the streaming indexer in `src/vaultspec_rag/indexer/_streaming.py` completely ignores this config. `_stream_encode_and_upsert_vault` and `encode_and_upsert_code_slice` unconditionally call `model.encode_documents_sparse(slice_texts)`. This forces SPLADE model loading and sparse vector computation on the GPU during every index run, wasting significant VRAM and compute even when the operator has explicitly disabled sparse features.

## MCP Deconflation-001 | CRITICAL | Benchmark and Quality tools bypass REST, violating process lock

In `src/vaultspec_rag/mcp/_admin_tools.py`, the `benchmark()` and `quality()` tools import and invoke `vaultspec_rag.run_benchmark()` and `vaultspec_rag.run_quality_probe()` directly inside the MCP process. This violates the server deconflation boundary. Worse, because these functions instantiate a new `VaultStore`, they will crash with `VaultStoreLockedError` if the resident daemon is running (as it holds the `exclusive.lock` on Qdrant). These tools must dispatch via REST to the daemon.

## MCP Deconflation-002 | MEDIUM | Log reading tool bypasses REST API

In `src/vaultspec_rag/mcp/_admin_tools.py`, the `get_logs()` tool uses a direct local thread call (`read_service_log(lines)`) instead of routing through `_call_daemon("/logs")`. An inline comment notes this was done because `/logs` returns a `PlainTextResponse` while `_call_daemon` expects JSON. This violates the separation of concerns between MCP and the service runtime. The server should expose a JSON-formatted log endpoint to ensure all MCP interactions flow through the canonical daemon REST boundary.
