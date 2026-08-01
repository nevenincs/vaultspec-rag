---
tags:
  - '#exec'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
body_hash: 'sha256:3895a45e44e5b896dd6d49c7ce912412d4eee3d7f259782b6fa23d1c92ac2afa'
step_id: 'S05'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# Run lint, type check, and the search and transport test suite

## Scope

- `pyproject.toml`

## Description

- Run ruff and basedpyright on the changed module and tests (clean).
- Run the new suite plus the existing search, transport, and CLI suites; root-cause the three batch failures (two locked-store tests now assert the new contract; one slow service integration test was batch-contention, green alone and in its file group).

## Outcome

All targeted suites green; lint and type checks clean.

## Notes

CI uses basedpyright (stricter than local `ty`); the `@contextmanager` return type was set to `Generator[None]` to satisfy it.
