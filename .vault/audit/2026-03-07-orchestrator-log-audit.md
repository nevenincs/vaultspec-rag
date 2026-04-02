---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-07
related: []
---

# Orchestrator Log

## 2026-03-07 — rag-orchestrator online

**Agent**: rag-orchestrator

---

### Corrected State

All tasks through #64 are **completed**. The entire backlog from audit rounds 1-20 has been addressed by coder. Issues previously flagged in the audit docs (byte-offset bug, tag filter, metadata filters, MCP query mutation, api.py facade, list_documents N+1, CrossEncoder batch_size, etc.) were all fixed in earlier task cycles.

Tasks #68-#79 were created in error from stale audit findings and have been **deleted**.

### Round 21 findings received (codebase-researcher)

Audit report: `docs/audit/2026-03-07-search-cli-mcp.md`

- 1 CRITICAL, 3 MAJOR, 12 MINOR findings across search.py, cli.py, mcp_server.py

Verified all critical/major items against current source code. Created 3 tasks:

| Task | Severity | Issue | Status |
|------|----------|-------|--------|
| #82 | CRITICAL | `get_code_file` symlink traversal bypass | assigned to coder |
| #83 | MEDIUM | `get_comp()` not thread-safe | assigned to coder |
| #84 | MEDIUM | MCP async tools block event loop | blocked by #83 |

**Not tasked (verified, low impact or by-design):**

- R21-M1: search_all() score mixing — known design limitation, no simple fix
- R21-M3: Graph rerank after CrossEncoder — intentional ordering (Task #59)
- R21-m1 through R21-m14: Minor style/usability issues, not blocking

### Round 22 findings (codebase-researcher-2)

Audit report: `docs/audit/2026-03-07-indexer-store-api.md`

- 6 MAJOR, 8 MINOR across indexer.py, store.py, api.py

Verified and sent to team-lead for task creation:

- R22-M4 [HIGH]: `_build_filter` uses `MatchText` for date — wrong semantics (store.py:657-662)
- R22-M6 [MEDIUM]: `api.get_engine` leaks old Qdrant client on root_dir change (api.py:53-54)
- R22-M5 [LOW]: `hybrid_search` calls `count()` on every query — redundant (store.py:517, 581)

Team-lead created tasks for these items.

### Round 22b findings (codebase-researcher-2)

Audit report: `docs/audit/2026-03-07-store-embeddings.md`

- 4 MAJOR, 14 MINOR across store.py, embeddings.py

Result: **No new tasks needed.**

- R22b-M1/M2/M3: Duplicates of R22-M4/M5/M6 (already tasked)
- R22b-M4 (encode_documents omits prompt_name): **FALSE POSITIVE** — verified against Research Topic 12. Qwen3 documents correctly use no prompt; queries use `prompt_name="query"`. Code is correct.

### Round 23 findings (codebase-researcher-2)

Audit report: `docs/audit/2026-03-07-indexer-round23.md`

- 4 MAJOR, 8 MINOR in indexer.py (deep dive on `_scan_codebase`, `TextSplitter`, incremental hashing)

Verified against current source code. Sent to team-lead for task creation:

| Finding | Severity | Issue | File |
|---------|----------|-------|------|
| R23-M1 | HIGH | `_scan_codebase` rglob traverses ignored dirs (`.venv/`, `node_modules/`) — pathspec only filters after full walk | indexer.py:903 |
| R23-M2 | HIGH | `VaultIndexer.incremental_index` uses unreliable `st_mtime` float comparison (2s resolution on Windows FAT32); `CodebaseIndexer` correctly uses SHA-256 | indexer.py:741-743 |
| R23-M3 | HIGH | `_chunk_with_splitter` line tracking wrong when `content.find()` returns -1 — falls back to previous chunk's end position | indexer.py:998-1004 |
| R23-M4 | MEDIUM | `TextSplitter` overlap prepends tail of chunk N to chunk N+1, causing duplicate content in embeddings and inflated search results | indexer.py:133-134 |
| R23-m7 | MEDIUM | `prepare_document` uses `path.stem` as doc ID — not unique across directories (`docs/adr/overview.md` and `docs/research/overview.md` both get ID `"overview"`) | indexer.py:592 |

**Not tasked (low impact or acceptable):**

- R23-m1: Nested gitignore scoping narrower than git's behavior — edge case
- R23-m2: `_is_binary` silently treats unreadable files as binary — should log but not critical
- R23-m3: Incremental index counts overstate when `prepare_document` returns None — cosmetic
- R23-m4: Delete-before-upsert ordering not crash-safe — acceptable risk
- R23-m5: Symlink loops in rglob — Python 3.13 handles this
- R23-m6: TextSplitter force-split overlap — intentional for text continuity
- R23-m8: ThreadPoolExecutor default thread count — optimization, not a bug

### Research Topics 15-16 (docs-researcher-2)

- **Topic 15 (score normalization):** RRF scores ~[0.05, 0.7] and CrossEncoder logits ~[-12, +12] are on incomparable scales. Fix: sigmoid normalization on CrossEncoder logits + min-max normalization + weighted combination. Relevant to R21-M1 (`search_all` score mixing).
- **Topic 16 (MCP async patterns):** MCP SDK PR #1909 auto-wraps sync `def` tools in `anyio.to_thread.run_sync()`. Simplest fix for R21-M6: convert `async def` tools to plain `def` instead of adding manual `asyncio.to_thread()` wrappers.

### Task status update

All R23 items tasked by team-lead as #42-#45. Round 21 items tasked as #82-#84 (pending).

### 2026-03-08 session resume

Picked up from context compaction. Status review:

- Tasks #11, #15, #21 marked completed (already done in code/audits)
- Task #17 (watcher): watcher.py existed but was missing cooldown — added 30s application-level cooldown via `time.monotonic()` timestamp comparison
- Task #15 regression fixed: removing "server" from early return broke `server --help`. Proper fix: kept "server" in early return, added `VAULTSPEC_ROOT` propagation in `mcp_start` via `ctx.find_root().params.get("target")`
- Task #23 (CRITICAL): git-added 21 untracked test corpus files
- Task #24: Added `test-project/.vault/logs/.gitignore` to exclude *.jsonl
- Ruff violation in mcp_server.py fixed: `_MAX_READ_SIZE` → `max_read_size`
- 195 unit tests passing, ruff clean

### Completed this session (2026-03-08)

- #17: watcher.py cooldown added (30s application-level via time.monotonic)
- #15 regression fixed: "server" back in early return; mcp_start propagates --target→VAULTSPEC_ROOT via ctx.find_root()
- #23: 21 untracked GPU_FAST_CORPUS_STEMS files staged
- #24: .vault/logs/.gitignore added
- #20: metrics.py + test_metrics.py (precision_at_k, reciprocal_rank, ndcg_at_k)
- #28: EmbeddingModel shared across all 5 fixtures (one session-scoped instance)
- Integration/conftest.py docstring: "unit" → "integration"
- 207 unit tests passing, ruff clean

### Audit cycle 2 results (2026-03-08)

- ADR anchor audit: ALL 12 ADRs verified. 2 flagged as "not implemented" were false positives (blake2b IS in indexer.py, Path.resolve() IS in api.py line 64).
- search.py/embeddings.py: PASS — no CRITICAL/HIGH issues. 2 MEDIUM: search_all() docstring (fixed by coder-2), separate normalization weighting.
- Test mandate compliance: 100% — 0 violations across 27 files.
- Indexer audit: 2 R23 bugs FIXED (mtime→blake2b, stem→relative path), os.walk pruning in place. Task #40 was false positive (metadata write is correct). #41 (line tracking) and #42 (overlap=0 doc) assigned to coder-3.
- CLI shape gaps: #34 (search --type all) and #36 (MCP GPU status) completed by coder-2.

### Active agents (2026-03-08 cycle 3)

- **codebase-researcher-4**: test mandate compliance (DONE — 0 violations)
- **coder-3**: Fix indexer line tracking (#41) + overlap=0 comment (#42)
- **coder-4**: Implement CLI-as-MCP-client fast path (#19)
- **codebase-researcher-5**: Indexer correctness audit (DONE)

### 2026-03-08 session resume (cycle 4 — post-compaction)

**Critical regression fixed immediately:**

- `"server"` was stripped from the `invoked_subcommand` early-return tuple at cli.py:129 by a ruff --fix save hook. Re-added manually. 207 unit tests confirm green.

**Task completions verified:**

- #41 (coder-3): line tracking fix in `_chunk_with_splitter` — DONE
- #42 (coder-3): chunk_overlap=0 comment — DONE
- #19 (coder-4): CLI-as-MCP-client fast path — DONE (`_try_mcp_search`, `_display_search_results`, `--port` on `handle_search`)
- #35: code search filters (language, node_type, function_name, class_name) — already DONE
- #43: Atomic writes to both `VaultIndexer._write_meta` and `CodebaseIndexer._write_meta` — DONE (write-to-.tmp + os.replace)

**Test fix:**

- `test_mcp_server.py::TestPydanticModels::test_index_status` was failing — `IndexStatus` now requires `target_dir` (added in #36). Test updated to include `target_dir="/tmp/workspace"`.

**State:** 207 unit tests passing, ruff clean.

### Cycle 4 agent results

**codebase-researcher-6 (Round 24):** `docs/audit/2026-03-08-watcher-clipath-audit.md`

- M1: `asyncio.run()` from sync CLI context — acceptable (CLI handlers always sync). Added docstring clarification to `_try_mcp_search`.
- M2: MCP response shape uses `.get()` fallback — acceptable (graceful degradation).
- L1-L3: Cooldown logic, type safety, score handling — all verified correct.
- **No tasks created** (all findings acceptable or by-design).

**compliance-researcher-2:** `docs/audit/2026-03-08-compliance-reaudit.md`

- 100% mandate compliance maintained across all 27 files.
- MODERATE gap: `_try_mcp_search` / `_display_search_results` have no unit tests → **Task #49 created**, assigned to coder-5.
- LOW gap: `_chunk_with_splitter` line tracking edge case — covered implicitly by integration tests, not tasked.

**docs-researcher-3:** MCP client API verification — still running.

### Cycle 4 completions

- **Task #49 (coder-5):** 8 unit tests added for `_try_mcp_search` + `_display_search_results` in `TestMcpFastPath` class. Two ruff fixes applied (unused `io` import, `ClassVar` annotation on class-level `pytestmark`).
- **215 unit tests passing, ruff clean.**
- Stale messages from prior orchestrator/coder session instances triaged — no new work required.

### Cycle 5 results

**docs-researcher-3 (Topic 17 — MCP client API):** ALL 6 implementation points CORRECT.

- `streamable_http_client` import path ✅, context manager tuple ✅, ClientSession API ✅, `result.content[0].text` ✅, `/mcp` endpoint path ✅, `asyncio.run()` safety ✅. No fixes needed.

**codebase-researcher-7 (Round 25 — store.py + api.py):** PASSED.

- All previously-reported fixes verified in place. 1 MEDIUM (doc_id vs chunk_id naming asymmetry) — design clarity only, no bug. No new tasks created.

**coder-5 (Task #49):** Confirmed — 8 tests added, 215 unit tests passing.

**Stale messages from prior session agents** (coder, codebase-researcher, orchestrator v1): All confirmed previously-completed tasks. No new work required.

### Cycle 6 partial results

**docs-researcher-4 (Topic 18 — Qdrant filter API):** ALL CORRECT ✅

- MatchValue for KEYWORD exact match ✅, Prefetch filter per-Prefetch ✅, RRF k=60 ✅, collection schema ✅
- Written to: `docs/research/2026-03-08-qdrant-filter-verification.md`

**Metadata merge sanity check (triggered by stale coder "Task #40 reverted" message):**

- Current code at indexer.py:804 writes `current_hashes` directly — CORRECT. `current_hashes` is computed over ALL current files (lines 757-765), so it captures the complete correct state. Deleted files are absent from `current_docs` and thus absent from `current_hashes`. No regression.

**Stale old-session agent chatter (orchestrator v1, coder v1):** Looping on Task #15/#28/#40 confirmations. All verified correct. Ignoring.

### Cycle 6 final results

**codebase-researcher-8 (Round 26 — embeddings.py):** PASS ✅

- SPLADE asymmetry verified at 10 call sites. CrossEncoder sigmoid correct. OOM backoff in place. Thread-safe.

**codebase-researcher-9 (Round 27 — search.py):** PASS ✅

- All flows correct. score_all() min-max handles equal scores. Graph rerank safe on empty graph. 1 LOW: snippet truncation on very short content — expected behavior, no action.

**No new tasks from R26 or R27.** All core RAG modules now audited clean.

### Audit coverage summary (2026-03-08)

| Module | Round | Status |
|--------|-------|--------|
| indexer.py | R23 + correctness | ✅ PASS |
| store.py | R25 | ✅ PASS |
| api.py | R25 | ✅ PASS |
| embeddings.py | R26 | ✅ PASS |
| search.py | R27 | ✅ PASS |
| cli.py | R21 + R24 | ✅ PASS |
| mcp_server.py | R28 pending | 🔄 |
| config.py | R28 pending | 🔄 |
| watcher.py | R24 + R28 pending | 🔄 |

### Cycle 7 result

**codebase-researcher-10 (Round 28 — mcp_server.py + config.py + watcher.py):** CLEAN ✅

- Module-level asyncio primitives safe (Python 3.10+). Double-checked locking sound. GPU semaphore granularity correct. Watcher cooldown correct. Error propagation transparent. Path defaults match usage.

### Full audit coverage complete ✅ (2026-03-08)

| Module | Round | Status |
|--------|-------|--------|
| indexer.py | R23 + correctness | ✅ PASS |
| store.py | R25 | ✅ PASS |
| api.py | R25 | ✅ PASS |
| embeddings.py | R26 | ✅ PASS |
| search.py | R27 | ✅ PASS |
| cli.py | R21 + R24 | ✅ PASS |
| mcp_server.py | R28 | ✅ PASS |
| config.py | R28 | ✅ PASS |
| watcher.py | R24 + R28 | ✅ PASS |

**Final state: 215 unit tests passing, ruff clean.**

### Round 29 cross-module audit triage

**codebase-researcher-11 (Round 29):** 3 findings:

- R29-C1 (drop→search race, clean=True): Downgraded to MEDIUM. Rare admin op; Qdrant error propagates cleanly. Acceptable risk. Not tasked.
- R29-C2 (metadata loss on exception): **FALSE POSITIVE** — Task #43 atomic write already mitigates. If `os.replace` fails, old meta intact → no duplicate indexing.
- R29-H3 (graph cache stale 5min after reindex): **FIXED** — added `comp.searcher._graph_built_at = 0.0` in `reindex_vault._run()`. Graph rebuilds on next search call.

### Cycle 8 result

**docs-researcher-5 (Topic 19 — FastMCP lifespan):** CLOSE Task #25 as "Not Beneficial"

- Lifespan forces 5-15s eager GPU init at startup vs current <100ms.
- Lifespan crashes server on init failure; current approach caches error and stays alive.
- Both approaches still need threading.Lock + asyncio.Semaphore(1). Lifespan adds no thread-safety benefit.
- **Task #25 deleted.**

### Pending tasks

None. All confirmed bugs fixed. All modules audited clean.

### State (2026-03-09)

- **215 unit tests passing, ruff clean**
- All 9 modules audited across R21-R29
- Task #25 closed as "not beneficial" (lazy-init is strictly better than lifespan for this architecture)
- MEMORY.md updated with complete session state

### Cycle 9 partial result

**codebase-researcher-12 (Round 30):** All new code correct ✅. 3 regression test gaps:

- Graph cache invalidation (reindex_vault._run) — no ADR test
- asyncio.run() in _try_mcp_search — no ADR test
- os.replace in both _write_meta implementations — no ADR test
→ **Task #60 created**, assigned to coder-6.

### Cycle 9 final results

**docs-researcher-6 (Topic 20 — watchfiles API):** ALL CORRECT ✅

- `debounce` param = ms (int), default 1600ms, current 2000ms intentional ✅
- `stop_event` accepts asyncio.Event ✅
- `Change` IntEnum (added=1, modified=2, deleted=3) ✅
- No code changes needed.

### Cycle 10 result

**coder-6 (Task #60):** 4 unit tests added to test_adr_regression.py. **219 unit tests passing, ruff clean.**

- TestGraphCacheInvalidation: reindex_vault resets_graph_built_at=0.0 ✅
- TestCliMcpFastPath: _try_mcp_search uses asyncio.run() ✅
- TestAtomicMetaWrite: VaultIndexer + CodebaseIndexer _write_meta use os.replace() ✅

### State (2026-03-09)

- **219 unit tests passing, 0 ruff violations**
- All 9 modules audited R21-R29, all clean
- No pending tasks

### Cycle 11 results

**codebase-researcher-13 (Round 31 — test infra):** PASSED ✅

- Fixtures correct: 1 shared EmbeddingModel (5 variants), 5 unique Qdrant suffixes, proper teardown.
- Compliance: 100% clean (spot-check confirms no new violations).
- 3 MEDIUM integration coverage gaps (noted, not blocking); 1 LOW: benchmark conftest creates duplicate EmbeddingModel.
- → Task #64 created + assigned to coder-7.

### Cycle 12 partial result

**docs-researcher-7 (Topic 21 — Qwen3 task prefixes):** ALL CORRECT ✅

- Document prompt = "" (empty), query prompt = "Instruct:...", batch uniform application ✅
- SPLADE encode_document()/encode_query() asymmetric routing ✅
- No code changes needed.

### Cycle 12 final

**coder-7 (Task #64):** benchmark conftest now passes `model=embedding_model` to `_build_rag_components`. **219 passing, ruff clean.**

### State (2026-03-09)

- **219 unit tests passing, 0 ruff violations**
- All modules + test infra audited R21-R31, all clean
- No pending tasks

### Cycle 13 results

**codebase-researcher-14 (Round 32 — security/errors):**

- C1 (--target no workspace validation): **FALSE POSITIVE** — `resolve_workspace` raises `WorkspaceError` if no `.vaultspec/` found; already validates.
- C2 (api.get_engine any dir): **BY-DESIGN** — internal API, not user-facing.
- H1 (_comp_error permanent cache): **BY-DESIGN** — documented; restart required after init failure.
- H2 (full reindex race): Known from R29, acceptable risk.
- M1 (query length unbounded): **FIXED** — added `_validate_query()` that truncates at 10K chars + logs warning. Applied to all 3 search tools.
- M2 (filter param length): FALSE POSITIVE — Qdrant handles safely, no injection.
- M3 (error message disclosure): BY-DESIGN — local tool, no untrusted users.

**Net: 1 genuine fix (M1 query length guard). All other findings are false positives or by-design.**

**219 unit tests passing, ruff clean.**

### State (2026-03-09)

- **219 unit tests passing, 0 ruff violations**
- All modules audited R21-R32, all clean
- No pending tasks

### Round 33 triage (2026-03-09)

**codebase-researcher-15-2 (R33 — performance):** Report: `docs/audit/2026-03-09-performance-round33.md`

| Finding | Verdict | Action |
|---------|---------|--------|
| C1: graph cache not invalidated after reindex_codebase | **FALSE POSITIVE** — VaultGraph reads vault docs only; code reindex doesn't affect vault cross-links | None |
| A5: partial upsert on failure | Design limitation — full_index(clean=True) is recovery path | None |
| A2: all docs in memory during full_index | Acceptable — 213-doc corpus; not a current bug | None |
| B4: search_all() sequential | **BY-DESIGN** — GPU semaphore serializes anyway | None |
| C3: max_query_length hardcoded | LOW — could move to config; not a bug | None |

**Net: 0 tasks created from R33.**

**docs-researcher-8-2 (Topic 22 — embeddings OOM/batch):** ALL CORRECT ✅

- OOM backoff: exponential retry (batch_size // 2), min enforcement, cuda.empty_cache() ✅
- Dense batch_size=64 (config-driven), sparse=32 (per-call) ✅
- normalize_embeddings=True in all dense paths ✅
- flash attention probed at load time, gracefully optional ✅
- No code changes needed. Report: `docs/research/2026-03-09-embeddings-oom-verification.md`

**Awaiting:** compliance-researcher-3 (integration coverage + compliance re-check)

### Round 35-36 triage (2026-03-09)

**R35 codebase-researcher-17:**

- api.py graph invalidation: api.index() already calls _graph_cache.invalidate() ✅; index_codebase() skip is BY-DESIGN. No task.
- search_all() double encoding: CONFIRMED. → Task #79 (coder-9-2) — in flight.

**R36 codebase-researcher-18:** Report: `docs/audit/2026-03-09-graph-embedding-round36.md`

- Query embedding pipeline: CORRECT ✅ (prompt_name="query" applied, filter tokens removed before encoding)
- SPLADE asymmetric dispatch: VERIFIED ✅
- Graph cache invalidation after reindex: CORRECT ✅
- CRITICAL (concurrent graph rebuilds at TTL boundary): KNOWN ISSUE — deferred to next session. Risk lower than reported: _gpu_sem serializes all MCP calls; race only exists via direct api.py multi-thread usage.
- MEDIUM (graph read mid-write): Mitigated by Task #43 atomic writes. No action.

### Shutdown state (2026-03-09)

**Final fixes this session:**

- Task #74: watcher graph cache invalidation (searcher passed to watch_and_reindex) ✅
- Task #75: reranker_batch_size config + OOM backoff ✅
- Task #79: search_all() double encoding refactor — in progress (coder-9-2)

**Known deferred issues:**

- R36-C1: threading.Lock around _get_graph() rebuild (low real-world risk due to _gpu_sem, but architecturally unsound for direct api.py callers)

**Team deletion pending after Task #79 completes.**

### Round 34 — graph/batch/reranker domain (2026-03-09)

Audit focus: watcher→graph invalidation gap, CrossEncoder OOM, batch sizes on 4080 16GB.

**Pre-triage (orchestrator-verified before agent report):**

**R34-H1 CONFIRMED — Watcher vault reindex does NOT invalidate graph cache:**

- `watch_and_reindex()` signature in watcher.py takes `vault_indexer` + `code_indexer` but NOT `searcher`
- After watcher calls `vault_indexer.incremental_index()`, no path exists to `searcher._graph_built_at = 0.0`
- `_comp.searcher` is available at the call site in mcp_server.py:_ensure_watcher() but not passed through
- Result: file changes caught by watcher leave stale graph boost scores for up to 300s (graph_ttl_seconds)
- Fix: add `searcher: VaultSearcher | None = None` param to `watch_and_reindex`; set `searcher._graph_built_at = 0.0` after vault reindex; pass `_comp.searcher` at call site

**codebase-researcher-16 (R34):** Report: `docs/audit/2026-03-09-graph-reranker-round34.md`

- CRITICAL 1+2 (watcher/searcher gap): CONFIRMED → Task #74 (coder-8) ✅ FIXED
- HIGH (CrossEncoder no OOM backoff): CONFIRMED → Task #75 (coder-9) ✅ FIXED
- MEDIUM (graph threading): NOT AN ISSUE — GPU semaphore serializes all calls

**docs-researcher-9 (Topic 23 — batch sizes on 4080 16GB):** ALL SAFE ✅

- Combined peak ~4 GB (25%) of 16 GB — 12 GB headroom. No urgent changes.
- `reranker_batch_size` config: added in Task #75.
- Report: `docs/research/2026-03-09-batch-size-16gb-research.md`

**State after R34: 220 unit tests passing, 0 ruff violations**

### Role

1. Direct researchers to targets
2. Read and verify findings against current code
3. Create tasks for confirmed issues
4. Update this log
