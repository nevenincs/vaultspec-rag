---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Add bounded nonterminal admission and cooperative shutdown timing settings using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add a positive 64-job admission bound for exact-addressable nonterminal work.
- Add a finite positive 300-second cooperative shutdown window.
- Map both settings through the canonical environment-variable registry and RAG defaults.
- Validate resolved values before downstream lifecycle components consume them.

## Outcome

The service configuration now exposes `job_max_nonterminal` and
`job_shutdown_timeout_seconds` with bounded defaults, canonical environment mappings, and
fail-fast validation. Imported production probes confirmed defaults, environment coercion,
and invalid-value rejection. Ruff formatting and lint, ty, and BasedPyright passed.

## Notes

Job-manager admission, shutdown orchestration, and production-behavior tests remain assigned
to later plan Steps. No data was changed and no scaffold remains in production code.
