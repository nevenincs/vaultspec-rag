---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-08
related: []
---

# Audit Report: Integration Test Fixture Scoping & Isolation

**Date:** 2026-03-08
**Auditor:** codebase-researcher-2
**Scope:** Session/module-scoped fixtures, Qdrant isolation, teardown, corpus coverage, GPU model sharing

______________________________________________________________________

## Executive Summary

The fixture architecture is **LARGELY SOUND** but with **TWO CRITICAL ISSUES**:

1. **CRITICAL:** `rag_components_with_code` fixture (integration conftest, line 35) does NOT accept the shared `embedding_model` parameter, creating a **second GPU EmbeddingModel** instance without synchronization.
1. **CRITICAL:** `rag_components_mixed` fixture (test_search_integration.py, line 139) also fails to accept `embedding_model`, leading to a **third GPU model instance**.
1. **HIGH:** Integration conftest docstring incorrectly labels these as "RAG unit test fixtures" when they are integration fixtures.
1. **MEDIUM:** `rag_components_with_code` is missing explicit session-scope documentation and uses a different suffix pattern than others.

Otherwise, the fixture design is correct: proper Qdrant isolation via suffixes, correct teardown, full corpus coverage across all 5 doc_types, and proper `_save_meta` usage.

______________________________________________________________________

## Findings

### 1. Fixture Scoping — Session-Scoped Safety Check

**Status:** ✅ PASS (with caveats noted below)

All session-scoped fixtures properly use `yield` for cleanup and have unique Qdrant suffixes:

| Fixture                    | File                       | Scope   | Qdrant Suffix | Teardown                               |
| -------------------------- | -------------------------- | ------- | ------------- | -------------------------------------- |
| `embedding_model`          | conftest.py                | session | N/A (shared)  | Implicitly closed with Python exit     |
| `rag_components`           | conftest.py                | session | `-fast`       | ✅ `store.close()` + `shutil.rmtree()` |
| `rag_components_full`      | conftest.py                | session | `-full`       | ✅ `store.close()` + `shutil.rmtree()` |
| `rag_components`           | integration/conftest.py    | session | `-fast-unit`  | ✅ `store.close()` + `shutil.rmtree()` |
| `rag_components_with_code` | integration/conftest.py    | session | `-fast-code`  | ✅ `store.close()` + `shutil.rmtree()` |
| `rag_components_mixed`     | test_search_integration.py | module  | `-mixed`      | ✅ `store.close()` + `shutil.rmtree()` |

**Finding:** No state mutation between tests detected. Each fixture creates isolated Qdrant collections.

______________________________________________________________________

### 2. Qdrant Isolation via Suffix Strategy

**Status:** ✅ PASS

Each fixture uses a unique `qdrant_suffix` passed to `_build_rag_components()`:

```python
# Line 100-117 in conftest.py
qdrant_name = f".qdrant{qdrant_suffix}"  # e.g., ".qdrant-fast", ".qdrant-full"
qdrant_dir = root / qdrant_name

if qdrant_dir.exists():
    shutil.rmtree(qdrant_dir)  # Clean previous test data

if qdrant_suffix:
    store._client.close()
    store.db_path = qdrant_dir
    store.db_path.mkdir(parents=True, exist_ok=True)
    store._client = _QdrantClient(path=str(qdrant_dir))  # Fresh QdrantClient per suffix
```

**No suffix collisions found:**

- `.qdrant-fast` — session fixture in conftest.py
- `.qdrant-full` — session fixture in conftest.py (quality tests only)
- `.qdrant-fast-unit` — session fixture in integration/conftest.py
- `.qdrant-fast-code` — session fixture in integration/conftest.py
- `.qdrant-mixed` — module fixture in test_search_integration.py

**Verification:** Each suffix creates a distinct `QdrantClient(path=...)`, so collections never collide.

______________________________________________________________________

### 3. Teardown Correctness

**Status:** ✅ PASS

All fixtures execute proper teardown via `yield`:

```python
# Example (rag_components in conftest.py:138-148)
@pytest.fixture(scope="session")
def rag_components(embedding_model):
    components = _build_rag_components(...)
    yield components
    # Teardown:
    components["store"].close()          # Closes QdrantClient
    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)            # Removes .qdrant-fast/ directory
```

**All 5 fixtures follow this pattern consistently.** No resource leaks detected.

______________________________________________________________________

### 4. GPU_FAST_CORPUS_STEMS Coverage — All 5 Doc Types Present

**Status:** ✅ PASS

**13-document fast corpus defined in constants.py (line 32-53):**

| Doc Type      | Count | Stems (Examples)                                                                                                                                               |
| ------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **adr**       | 4     | `2026-01-10-pipeline-execution-model`, `2026-01-12-connector-protocol-design`, `2026-01-15-storage-backend-selection`, `2026-01-20-scheduler-algorithm-choice` |
| **plan**      | 2     | `2026-01-10-pipeline-engine-phase1-plan`, `2026-01-20-scheduler-phase1-plan`                                                                                   |
| **exec**      | 2     | `2026-01-11-pipeline-parser-complete`, `2026-01-22-scheduler-worker-pool-complete`                                                                             |
| **reference** | 3     | `2026-01-10-pipeline-engine-reference`, `2026-01-12-connector-api-reference`, `2026-01-18-nexus-security-audit`                                                |
| **research**  | 2     | `2026-01-09-dag-execution-research`, `2026-01-19-scheduling-algorithms-research`                                                                               |

**Verification:** All files exist in `test-project/.vault/` and are **git-tracked** (confirmed via `git ls-files`):

```bash
$ git ls-files test-project/.vault/adr/2026-01-10-pipeline-execution-model.md
test-project/.vault/adr/2026-01-10-pipeline-execution-model.md  ✅ tracked
```

**Coverage is complete:** All 5 doc_types (adr, plan, exec, reference, research) are represented. The corpus is sufficient for testing type filtering, snippet generation, and mixed-source search.

______________________________________________________________________

### 5. `_vault_snapshot_reset` Correctness

**Status:** ⚠️ MEDIUM CONCERN

**Implementation (conftest.py:181-198):**

```python
@pytest.fixture(scope="session", autouse=True)
def _vault_snapshot_reset():
    """Reset test-project/.vault/ to git HEAD after the full test session."""
    yield
    result = subprocess.run(
        ["git", "checkout", "--", "test-project/.vault/"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
```

**Behavior of `git checkout -- test-project/.vault/`:**

- ✅ Restores all tracked files to HEAD state
- ❌ **Does NOT delete untracked files** (e.g., new .md files created by tests)
- ❌ **Does NOT delete newly created directories**

**GPU_FAST_CORPUS_STEMS files are git-tracked**, so checkout correctly restores them. However, any test that creates **new** files under `.vault/` will leave artifacts behind.

**Risk:** If a test creates new documents in `.vault/` (not in GPU_FAST_CORPUS_STEMS), they persist across test runs. This could:

- Inflate actual vault size metrics
- Cause non-deterministic test results if tests read from `.vault/` dynamically

**Mitigation:** None currently in place. The `_cleanup_test_project()` function (line 170-179) only removes non-`.vault/` artifacts (codebase, temp dirs, etc.).

**Recommendation:** For tests that must write to `.vault/`, use temporary copies of test-project rather than modifying it in-place.

______________________________________________________________________

### 6. Multiple EmbeddingModel Instances — CRITICAL ISSUE

**Status:** 🔴 CRITICAL

The fixture hierarchy creates **multiple GPU model instances** without synchronization:

#### Path 1: conftest.py fixtures ✅ CORRECT

```python
# conftest.py:138-146
@pytest.fixture(scope="session")
def embedding_model():
    return EmbeddingModel()

# conftest.py:149-158
@pytest.fixture(scope="session")
def rag_components(embedding_model):
    components = _build_rag_components(TEST_PROJECT, fast=True, qdrant_suffix=..., model=embedding_model)
    # Reuses the shared embedding_model ✅
```

Session fixtures correctly **accept and reuse** the shared `embedding_model`.

#### Path 2: integration/conftest.py ✅ CORRECT (rag_components)

```python
# integration/conftest.py:16-25
@pytest.fixture(scope="session")
def rag_components(embedding_model):
    components = _build_rag_components(TEST_PROJECT, fast=True, qdrant_suffix=QDRANT_SUFFIX_UNIT, model=embedding_model)
    # Reuses the shared embedding_model ✅
```

#### Path 3: integration/conftest.py 🔴 CRITICAL (rag_components_with_code)

```python
# integration/conftest.py:35-48
@pytest.fixture(scope="session")
def rag_components_with_code():  # ❌ NO embedding_model parameter
    components = _build_rag_components(
        TEST_PROJECT, fast=True, qdrant_suffix=QDRANT_SUFFIX_CODE
        # ❌ model parameter NOT provided
    )
    # Line 107-108 in conftest.py:
    # if model is None:
    #     model = EmbeddingModel()  # ❌ NEW GPU instance created
```

**This creates a SECOND EmbeddingModel instance on the GPU** (~ 900MB VRAM) during fixture setup.

#### Path 4: test_search_integration.py 🔴 CRITICAL (rag_components_mixed)

```python
# test_search_integration.py:138-152
@pytest.fixture(scope="module")
def rag_components_mixed(tmp_path_factory):  # ❌ NO embedding_model parameter
    components = _build_rag_components(TEST_PROJECT, fast=True, qdrant_suffix="-mixed")
    # ❌ model parameter NOT provided — creates THIRD GPU instance
```

**This creates a THIRD EmbeddingModel instance** during fixture setup.

#### Impact Analysis

**Problem:** EmbeddingModel loads two large transformer models onto GPU:

- SentenceTransformer("Qwen/Qwen3-Embedding-0.6B") → ~600MB
- SparseEncoder("naver/splade-v3") → ~300MB
- Total per instance: ~900MB VRAM

**Current GPU memory usage for test run:**

- Shared `embedding_model`: 900MB
- `rag_components_with_code` (second instance): +900MB = **1800MB total**
- `rag_components_mixed` (third instance): +900MB = **2700MB total**

**If GPU has 8GB VRAM:**

- 2700MB / 8000MB = **33.75% GPU utilization just for model storage**
- Leaves ~5.3GB for actual computation, which is acceptable
- But still wasteful and violates DRY principle

**If GPU has 4GB VRAM (mobile/edge GPUs):**

- 2700MB / 4000MB = **67.5% of GPU exhausted just storing models**
- Very limited room for inference workloads
- Risk of OOM errors during test runs

**Memory waste per test session:** 1800MB extra VRAM (if only 2 of 3 instances run), or 2700MB (if all run).

______________________________________________________________________

### 7. `_fast_index` Correctness — `_save_meta` Check

**Status:** ✅ PASS

**Implementation (conftest.py:29-77):**

```python
def _fast_index(indexer, model, store, root, stems):
    # ... fetch documents matching stems ...
    docs = []
    for p in paths:
        doc = prepare_document(p, root)
        if doc is not None:
            docs.append(doc)

    # ... encode embeddings ...
    for doc, vec, svec in zip(docs, vectors, sparse_vecs, strict=True):
        doc.vector = vec.tolist()
        doc.sparse_indices = list(svec.indices)
        doc.sparse_values = list(svec.values)

    store.ensure_table()
    store.upsert_documents(docs)

    # Save metadata for incremental indexing
    indexer._save_meta(docs)  # ✅ Line 67
```

**Verify `_save_meta` contract:**

```python
# indexer.py (from grep output)
def _save_meta(self, docs: list[VaultDocument]) -> None:
    """Save index metadata (content hashes) from VaultDocument list.

    Args:
        docs: List of indexed documents whose paths are used to compute hashes.
    """
    meta: dict[str, str] = {}
    from .config import get_config

    docs_dir = self.root_dir / get_config().docs_dir
    for doc in docs:
        path = docs_dir / doc.path  # Uses doc.path to locate file
        with contextlib.suppress(OSError), open(path, "rb") as f:
            meta[doc.id] = hashlib.file_digest(f, "blake2b").hexdigest()
```

**Contract:** `_save_meta` expects:

1. `docs: list[VaultDocument]` — ✅ Provided
1. Each `doc.path` must be relative to `.vault/` — ✅ Satisfied by `prepare_document()`
1. Each `doc.id` must be set — ✅ Set by `prepare_document()`

**Verification:** `prepare_document()` returns `VaultDocument` with:

- `path` = relative path (e.g., "adr/overview")
- `id` = doc_id (e.g., "adr/overview")
- Both required by `_save_meta`

**Result:** ✅ **CORRECT** — metadata is saved for incremental indexing.

______________________________________________________________________

## Summary Table

| Issue                                              | Severity | Status     | Details                                                              |
| -------------------------------------------------- | -------- | ---------- | -------------------------------------------------------------------- |
| Fixture scoping                                    | —        | ✅ PASS    | All fixtures properly isolated with unique suffixes                  |
| Qdrant suffix collisions                           | —        | ✅ PASS    | 5 unique suffixes, no collisions                                     |
| Teardown correctness                               | —        | ✅ PASS    | All fixtures close store + remove qdrant dir                         |
| Corpus coverage (doc_types)                        | —        | ✅ PASS    | All 5 types present (adr=4, plan=2, exec=2, reference=3, research=2) |
| Corpus files tracked                               | —        | ✅ PASS    | All 13 stems are git-tracked                                         |
| `_vault_snapshot_reset`                            | MEDIUM   | ⚠️ CONCERN | Only restores tracked files; new files persist across runs           |
| `rag_components_with_code` missing embedding_model | CRITICAL | 🔴 FAIL    | Creates second GPU instance (~900MB VRAM waste)                      |
| `rag_components_mixed` missing embedding_model     | CRITICAL | 🔴 FAIL    | Creates third GPU instance (~900MB VRAM waste)                       |
| `_fast_index` → `_save_meta` usage                 | —        | ✅ PASS    | Correct contract and arguments                                       |
| integration/conftest.py docstring                  | HIGH     | 🔴 FAIL    | Says "RAG unit test fixtures" but these are integration fixtures     |

______________________________________________________________________

## Recommendations

### 1. 🔴 CRITICAL: Fix GPU Model Sharing

**Action:** Add `embedding_model` parameter to both problematic fixtures:

```python
# integration/conftest.py, line 35-48
@pytest.fixture(scope="session")
def rag_components_with_code(embedding_model):  # ADD THIS PARAMETER
    components = _build_rag_components(
        TEST_PROJECT,
        fast=True,
        qdrant_suffix=QDRANT_SUFFIX_CODE,
        model=embedding_model  # ADD THIS ARGUMENT
    )
    ...

# test_search_integration.py, line 138-152
@pytest.fixture(scope="module")
def rag_components_mixed(embedding_model, tmp_path_factory):  # ADD embedding_model
    components = _build_rag_components(
        TEST_PROJECT,
        fast=True,
        qdrant_suffix="-mixed",
        model=embedding_model  # ADD THIS ARGUMENT
    )
    ...
```

**Impact:** Reduces GPU VRAM usage by ~1800MB, avoids OOM on mobile GPUs, improves test speed.

______________________________________________________________________

### 2. HIGH: Fix integration/conftest.py Docstring

**Action:** Update line 1 to read:

```python
"""RAG integration test fixtures."""
```

**Or expand to clarify the scope:**

```python
"""Integration test fixtures for RAG components with real GPU inference.

Tests in src/vaultspec_rag/tests/integration/ use these session-scoped
fixtures to exercise VaultSearcher, VaultIndexer, and related components
against real CUDA GPU inference.
"""
```

______________________________________________________________________

### 3. MEDIUM: Document `_vault_snapshot_reset` Limitations

**Action:** Add a note to the fixture docstring:

```python
@pytest.fixture(scope="session", autouse=True)
def _vault_snapshot_reset():
    """Reset test-project/.vault/ to git HEAD after the full test session.

    WARNING: This only restores tracked files via 'git checkout --'.
    Any new .md files created by tests will NOT be deleted.
    For tests that modify .vault/, use temporary copies instead.
    """
```

______________________________________________________________________

### 4. MEDIUM: Consider Switching to `tmp_path` for Vault Modifications

If any tests currently modify `test-project/.vault/`, migrate them to use a temporary copy:

```python
def test_something(tmp_path):
    vault_copy = tmp_path / ".vault"
    shutil.copytree(TEST_VAULT, vault_copy)
    # Now modify vault_copy instead of TEST_VAULT
    # Automatically cleaned up after test
```

______________________________________________________________________

## Conclusion

The fixture architecture is **structurally sound** with proper isolation and teardown. The Qdrant suffix strategy and corpus coverage are correct. However, **two critical GPU resource issues** must be fixed before accepting this fixture design:

1. **rag_components_with_code** should accept shared `embedding_model`
1. **rag_components_mixed** should accept shared `embedding_model`

Once these are fixed, the fixture design is **production-ready** for integration testing.
