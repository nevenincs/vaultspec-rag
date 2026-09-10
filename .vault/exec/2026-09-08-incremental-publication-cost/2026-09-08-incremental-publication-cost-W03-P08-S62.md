---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:1b3ac18a133d50e0f51b962401a96a9a30afe95c9a4f99b05b43785b98ccc6ea'
step_id: 'S62'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove explicit authority survives serialization, retry, restart, generic service admission, and CLI admission

## Scope

- `src/vaultspec_rag/tests/test_job_contracts_persistence.py`
- `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `src/vaultspec_rag/tests/test_cli_index.py`

## Changes

- `A` `.vault/audit/2026-09-09-incremental-publication-cost-s62-authority-lifecycle-audit.md`
- `M` `.vault/index/incremental-publication-cost.index.md`
- `M` `src/vaultspec_rag/tests/test_job_contracts_persistence.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `verify:` explicit-authority codec collapse mutation (4 failures) -> `fail`
- `verify:` authority-insensitive active-work identity mutation (2 failures) -> `fail`
- `verify:` retry authority rewrite mutation -> `fail`
- `verify:` persistence authority default/open-decoder mutation (6 failures) -> `fail`
- `verify:` generic service missing-authority default mutation -> `fail`
- `verify:` generic service forbidden-authority bypass mutation (2 failures) -> `fail`
- `verify:` CLI publication-authority collapse mutation -> `fail`
- `verify:` CLI full-audit conflict bypass mutation (3 failures) -> `fail`
- `verify:` restored three-file scoped pytest suite (175 passed) -> `pass`
- `verify:` `uv run --frozen ruff format --check <scoped Python files>` -> `pass`
- `verify:` `uv run --frozen ruff check <scoped Python files>` -> `pass`
- `verify:` `uv run --frozen ty check <scoped Python files>` -> `pass`
- `verify:` `uv run --frozen basedpyright <scoped Python files>` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` independent S62 authority-lifecycle review -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md --json` -> `pass`
- `verify:` `vaultspec-core vault check all --feature incremental-publication-cost --no-hints --json` -> `pass`
