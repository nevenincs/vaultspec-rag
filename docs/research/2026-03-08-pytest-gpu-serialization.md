# pytest GPU Test Serialization

**Date**: 2026-03-08
**Task**: #7
**Status**: Complete

## Current State

No problem to solve. The project doesn't use pytest-xdist. GPU tests already run sequentially in a single process via `pytest -m integration`.

## If xdist Is Added Later

Use `@pytest.mark.xdist_group("gpu")` + `--dist loadgroup`:

```python
# conftest.py — auto-tag GPU-bound markers
def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.iter_markers(name=m) for m in
               ("integration", "quality", "performance", "robustness")):
            item.add_marker(pytest.mark.xdist_group("gpu"))
```

Run with: `pytest -n auto --dist loadgroup`

- All `xdist_group("gpu")` tests run on one worker (serialized)
- CPU unit tests distribute across other workers (parallel)
- Built into pytest-xdist, no new dependency
- Industry standard (HuggingFace Transformers, FastAI, TVM)

## Options Evaluated

| Option | Verdict |
|---|---|
| No xdist (current) | Already serial. No action needed. |
| `xdist_group("gpu")` + `loadgroup` | **RECOMMENDED if xdist added** |
| `--dist loadscope` | Groups by module — less precise |
| `pytest -n 1` | Defeats purpose of xdist |
| pytest-forked | **AVOID** — CUDA not fork-safe, crashes |
| pytest-isolate | No Windows support |
| pytest-order | Controls ordering, not parallelism |
| Session file lock | Works but wasteful |

## Critical Warning

**Never use pytest-forked with CUDA tests.** CUDA contexts are not fork-safe. Forking after CUDA init causes `RuntimeError: Cannot re-initialize CUDA in forked subprocess`. Both vllm and DeepSpeed hit this.
