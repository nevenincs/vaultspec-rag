---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:0ea6f3dc7b1508df20d8fe683c1c586bef12a3fe015705e44ac72f3e11a72989'
step_id: 'S14'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove a missing in-progress clean build is retired instead of publishing a partial replacement

## Scope

- `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`

## Description

- Open the resumed clean generation through `CodeGenerationLifecycle`.
- Remove only its private build collection while preserving old served code.
- Reopen the same lifecycle request and assert invalidation before reuse.

## Changes

- Added the private-build-loss lifecycle regression to the rebuild survivability suite.
- Reused the test helper's canonical clean-generation configuration for both direct and lifecycle opening.

## Outcome

The lost generation is invalidated, a new generation is opened, and the old served
collection cannot satisfy the private-build evidence check.

## Notes

The collection-backed integration selection is subject to the repository's compatible
resident-service guard; static checks still cover the authored test on this host.
