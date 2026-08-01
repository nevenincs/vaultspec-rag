---
tags:
  - '#reference'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:1cc532831178e86c617f8d6524ee11b90e3d643c2f7be77f0e53abf7cc16a3d1'
related: []
---

# `lint-defaults` reference: `ruff complexity`

This reference records the source and gate analysis for restoring Ruff's
upstream design-complexity defaults without weakening checks.

## Summary

The isolated upstream-threshold check reports 279 findings: 225 argument-count,
38 return-count, 13 statement-count, and 3 nested-block findings. The configured
gate deliberately carries higher temporary maxima in `pyproject.toml` while
selecting the same rules, so restoring the defaults requires source changes rather
than a configuration edit.

Argument-count remediation should model one cohesive operation as a frozen request
or configuration value, following the established patterns in
`vaultspec_rag.search._noise.NoisePolicy`,
`vaultspec_rag.indexer._consumer_pipeline.CodePipelineLimits`, and the indexer
checkpoint configuration types. Public boundary functions need one intentional
request value per operation, with all callers migrated in the same change; no
forwarding compatibility signatures should remain.

Return-, statement-, and nesting-count remediation should extract independently
named phases that preserve the existing ordering, error handling, and ownership.
The affected clusters include search, indexing, job management, watcher behavior,
command installation, server routes, and integration tests. The test changes must
continue to exercise the real production path rather than duplicate setup or
business logic.

The dedicated nesting gate is preview-only, while the other three rules are selected
in the standard Ruff configuration. Completion is therefore an isolated Ruff check
with upstream limits plus the ordinary project lint, type, and relevant behavior
tests.
