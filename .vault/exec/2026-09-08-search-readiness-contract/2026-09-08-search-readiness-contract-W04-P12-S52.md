---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:2230d4b33c827a9fcdad28045142a8560d1fce809da5a3792e8e57e1a85c1557'
step_id: 'S52'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Record accepted no-wait latency throughput limiter GPU queue and waiter-cleanup comparison output

## Scope

- `src/vaultspec_rag/tests/benchmarks/baselines`

## Changes

- `M` `src/vaultspec_rag/tests/benchmarks/baselines/search_readiness_471_cpu_control.json`
- `verify:` `uv run python -m json.tool src/vaultspec_rag/tests/benchmarks/baselines/search_readiness_471_cpu_control.json` -> `pass`
- `verify:` `uv run python -c <baseline acceptance assertions>` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/benchmarks/bench_concurrency.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

No explicitly compatible resident GPU service was supplied. Live-service latency, throughput,
limiter, and GPU-queue fields remain null; the record contains only measured CPU-control data.
