---
name: index-progress-bars reference audit
description: Current state of progress reporting in vaultspec-rag index pipeline (CLI, indexer, embeddings) — grounding for issue #62
tags:
  - '#reference'
  - '#index-progress-bars'
date: 2026-04-12
related:
  - '[[2026-04-12-index-progress-bars-adr]]'
---

# index-progress-bars reference audit

## rich usage in the CLI

**File:** `src/vaultspec_rag/cli.py`

Rich imports (L31, L42–43):

- L31: `from rich.console import Console`
- L42: `from rich.panel import Panel`
- L43: `from rich.table import Table`
- L439: `from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn` (lazy import inside `handle_index`)

Console initialization (L55):

- L55: `console = Console(legacy_windows=False)` — global instance, no `force_terminal` or `no_color` flags set.

Current Progress usage in index command (L439–447):

- L439–447: Single Progress instance created with SpinnerColumn, TextColumn (description), BarColumn, and percentage TextColumn.
- Progress tasks added at L454 (init), L493 (vault), L512 (code) — three separate task IDs.
- L473, L501, L518: `progress.advance()` called once per task after phase completes (batch advance, not per-document).

Current index output:

- L353: Dry-run mode prints count and file list (no progress bar).
- L392–432: MCP path returns early with summary table, skips in-process progress entirely.
- L454–485: Init phase displays "Initializing RAG components..." (total=3, advanced 3x).
- L493–507: Vault phase displays "Indexing documentation vault..." (total=1, advanced 1x), followed by console.log summary.
- L512–524: Codebase phase displays "Indexing codebase..." (total=1, advanced 1x), followed by console.log summary.
- L529–554: Final summary table printed after progress context closes.

No per-document progress reporting exists. Entire vault/codebase phases are coarse single-task bars.

## indexer loops

**File:** `src/vaultspec_rag/indexer.py`

### VaultIndexer

**Class definition:** L770–1043

Entry points:

- L807–887: `full_index(clean=False)` — full re-index of all vault documents.
- L889–983: `incremental_index()` — incremental index comparing hashes.

Full indexing flow (L807–887):

- L826: `scan_vault(self.root_dir)` — document discovery (external vaultspec_core call).
- L828–837: ThreadPoolExecutor parses documents in parallel via `prepare_document()` — no progress callback.
- L849–852: Dense and sparse embedding computed in one batch call per modality.
  - L851: `self.model.encode_documents(texts)` — batch call, no callback.
  - L852: `self.model.encode_documents_sparse(texts)` — batch call, no callback.
- L854–857: Vectors attached to docs in zip loop (serial).
- L860–873: Store drop/ensure/delete (serial, no logging).
- L875: `upsert_documents()` batch call.
- L877–887: Metadata write and result return.

Incremental indexing flow (L889–983):

- L910: `scan_vault(self.root_dir)` document discovery.
- L927–936: Hash all current docs serially (no progress).
- L945–956: ThreadPoolExecutor parses new+modified docs via `prepare_document()` — no progress callback.
- L959–966: Batch encode documents and vectors (no per-doc callback).
- L967–970: Upsert and delete (batch).
- L972–983: Metadata write and result return.

No observer/callback pattern. No parallelization for embedding phase (batch-only). GPU lock (`self._gpu_lock`) exists for thread-safe GPU access but no progress integration.

### CodebaseIndexer

**Class definition:** L1046–1610

Entry points:

- L1229–1238: `scan_files()` — returns list of indexable source files.
- L1393–1468: `full_index(clean=False)` — full re-index of all codebase.
- L1470–1562: `incremental_index()` — incremental index comparing hashes.

Full indexing flow (L1393–1468):

- L1408: `_scan_codebase()` scans files (L1180–1227, walks with gitignore/vaultragignore filters, no progress).
- L1413–1419: Hash all files serially (no progress).
- L1423–1426: ThreadPoolExecutor chunks files via `_chunk_file()` — no progress callback.
- L1438–1441: Batch encode chunks (no per-doc/per-file loop).
  - L1440: `encode_documents(texts)` batch call.
  - L1441: `encode_documents_sparse(texts)` batch call.
- L1442–1445: Attach vectors (serial zip).
- L1447–1454: Store drop/ensure/delete (batch).
- L1456: `upsert_code_chunks()` batch call.
- L1457–1468: Metadata write and result return.

Incremental indexing flow (L1470–1562):

- L1485: `_scan_codebase()` scan files.
- L1491–1500: Hash all files serially (no progress).
- L1516–1523: ThreadPoolExecutor chunks modified+new files — no progress callback.
- L1532–1545: Batch encode chunks.
- L1526–1529: Delete old chunks for modified files.
- L1550–1562: Metadata write and result return.

No observer/callback pattern. GPU operations batch-only, no per-item boundaries exposed.

## embedding loop structure

**File:** `src/vaultspec_rag/embeddings.py`

Batching interface (L261–307):

- L292–297: `encode_documents(texts, batch_size)` calls `self._dense_model.encode()` with a list of texts and batch_size.

  - L284–285: Default batch_size from config via `_default_batch_size()` (L152–160).
  - L148: `DEFAULT_BATCH_SIZE = 64`.
  - L295: `show_progress_bar=len(truncated) > 100` — sentence-transformers internal progress bar only for large batches.

- L332–371: `encode_documents_sparse(texts, batch_size)` with default batch_size = 32 (L336, hardcoded).

No per-item callback exposed. Single `.encode()` call ingests entire list with batch_size splitting internal to SentenceTransformer. Dense: `config.embedding_batch_size` (L158–160) or 64; Sparse: 32 hardcoded (L336).

Sentence-transformers internal progress bar (L295) is dense-only, not hooked by CLI.

## silence points

Silent phases (no user-visible output) in index command:

1. **Workspace resolution** (cli.py:L272)
1. **Config load** (cli.py:L246, L262)
1. **Dry-run scan** (cli.py:L357–360)
1. **MCP delegation** (cli.py:L376–389)
1. **VaultStore init** (cli.py:L455, store.py:L122–154)
1. **Store drop/ensure** (cli.py:L459–460, indexer.py:L860, L1448)
1. **GPU model load** (cli.py:L475, embeddings.py:L173–250)
1. **Vault document scan** (indexer.py:L826, L910)
1. **Codebase file scan** (indexer.py:L1408, L1485)
1. **Document/file hashing** (indexer.py:L927–936, L1413–1419, L1491–1500)
1. **Document parsing** (indexer.py:L828–837, L949–956)
1. **File chunking** (indexer.py:L1423–1426, L1520–1523)
1. **Embedding encoding** (embeddings.py:L292, L358)
1. **Store upsert/delete** (indexer.py:L875, L967, L1456, L1545)
1. **Metadata write** (indexer.py:L877, L972, L1457, L1550)
1. **Graph rebuild** (not in index command directly)

Total: 16 silent phases, each a candidate for progress reporting.

## multi-corpus orchestration

**File:** `src/vaultspec_rag/cli.py`

Index command orchestration (L279–555):

- L449–450: `do_vault` and `do_code` flags determined from `index_type` argument.
- L452: Single `with progress:` context opened.
- L491–507: If `do_vault`, sequential vault indexing with one task.
- L510–524: If `do_code`, sequential codebase indexing with separate task.

Sequential execution: Vault indexing completes before codebase starts. No concurrent calls. One Progress bar shared by both (L493, L512).

MCP path (L366–433) calls both sequentially with no concurrency.

Single UI bar sufficient (no stacking needed), but two distinct task IDs track vault/code independently.

## existing tests

**Test files:**

- `src/vaultspec_rag/tests/test_cli.py` — L88: `test_index_requires_workspace()` (error case only).
- `src/vaultspec_rag/tests/test_cli_warmup.py` — CLI warmup test (not index).
- `src/vaultspec_rag/tests/test_indexer_unit.py` — indexer unit tests.
- `src/vaultspec_rag/tests/integration/test_indexer_integration.py` — integration tests.
- `src/vaultspec_rag/tests/integration/test_codebase_integration.py` — codebase-specific integration tests.

No `GPU_FAST_CORPUS_STEMS` or similar fixture constants found in codebase.

## NO_COLOR / non-TTY handling

**File:** `src/vaultspec_rag/cli.py`

Console initialization (L55):

- `console = Console(legacy_windows=False)` — no `force_terminal`, `no_color`, or environment checks applied.

Windows UTF-8 setup (L34–40):

- Reconfigures sys.stdout/stderr to UTF-8 but does not check TTY status.

No TTY detection via `sys.stdout.isatty()` or environment variable checks for `NO_COLOR`, `FORCE_COLOR`, or `TERM`.

Rich's Console auto-detects TTY by default. Non-TTY rendering degrades gracefully (Rich strips ANSI codes automatically).
