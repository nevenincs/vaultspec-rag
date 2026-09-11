---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8f1841ab85ab80ef735275c9986b6b896c3894e7022d32c05c38f679c00fa8d3'
step_id: 'S51'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Add immediate readiness overhead and bounded-wait contention to the concurrency benchmark

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`

## Changes

- `M` `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`
- `verify:` `uv run python src/vaultspec_rag/tests/benchmarks/bench_concurrency.py --help` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The live service throughput cases were not executed because no compatible resident service was available; the CPU-only readiness control and loopback response-decoding smoke checks passed without GPU use.
