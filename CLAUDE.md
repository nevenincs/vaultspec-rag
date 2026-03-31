# CLAUDE.md — vaultspec-rag project instructions

## Testing Standards (MANDATORY — no exceptions)

### Absolute prohibitions
- **No mocks, patches, fakes, stubs, monkeypatches** — not in any form. No `unittest.mock`, no `pytest-mock`, no `MagicMock`, no `patch()`, no `monkeypatch` fixture, no `@patch` decorators.
- **No `unittest` imports** — `import unittest` or `from unittest import ...` is banned entirely. Pytest only.
- **No tautological tests** — tests that always pass regardless of implementation (e.g. asserting `True`, asserting the mock you just set up, testing nothing real) must be deleted.
- **No `pytest.skip()`**, `@pytest.mark.skip`, `skipIf`, `skipUnless` — if a test can't run on the current hardware, it should fail with a clear error, not silently skip.

### Test structure
- **Unit tests live alongside the module they test** — in `src/vaultspec_rag/tests/`. One test file per module: `test_embeddings.py` next to `embeddings.py`, etc.
- **Live integration tests** go in `src/vaultspec_rag/tests/integration/`.
- **The `tests/` directory at repo root is deprecated** — do not add new tests there. Migrate existing tests to `src/vaultspec_rag/tests/`.

### Live tests — no fakes
- RAG tests must exercise real hardware. If the test requires a GPU, it runs on a GPU or fails.
- No in-memory fakes substituting for real Qdrant collections.
- No synthetic embeddings substituting for real model output.
- Tests must use `EmbeddingModel()`, `VaultStore()`, `VaultIndexer()`, `VaultSearcher()` with real CUDA inference against the real `test-project/` corpus.

### pytest conventions
- **Markers** (defined in `pyproject.toml`):
  - `@pytest.mark.unit` — fast, no GPU, no network, no disk I/O beyond fixtures
  - `@pytest.mark.integration` — requires CUDA GPU + Qdrant + real model inference
  - `@pytest.mark.quality` — full 213-doc corpus, precision/recall assertions
  - `@pytest.mark.performance` — benchmarking, throughput, latency
  - `@pytest.mark.robustness` — edge cases, error handling with real inputs
- Every test must have exactly one marker.
- Use `pytest-timeout` for integration tests. Default 300s.
- Use `pytest-asyncio` for async tests (`asyncio_mode = "auto"`).
- No `pytest-mock`. No `responses`. No `httpretty`.

### CLI test runner
- `vaultspec-rag test [PYTEST_ARGS...]` must be implemented in `cli.py`
- Passes all args through to pytest: `vaultspec-rag test -m integration -v --timeout=120`
- Internally calls `pytest src/vaultspec_rag/tests/ [args]`

## Architecture

### GPU-only — no CPU inference
- No fastembed, no ONNX, no CPU embedding fallback.
- `EmbeddingModel` raises `RuntimeError` if no CUDA GPU.
- Dense: `SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", torch_dtype=float16, flash_attention_2)`
- Sparse: `SparseEncoder("naver/splade-v3", device="cuda")`
- CrossEncoder reranker: `CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda")` (opt-in via `reranker_enabled`)

### Vector store
- Qdrant local mode (`QdrantClient(path=...)`) — no Docker required.
- Named vectors: `dense` (1024d) + `sparse` (SPLADE).
- Hybrid search via Qdrant Universal Query API + FusionQuery(RRF).

### Code standards
- Python 3.13, strict typing (no bare `Any`).
- ruff-compliant (line-length=88, target py313).
- No print statements — use logging.
- No backwards-compat shims.
