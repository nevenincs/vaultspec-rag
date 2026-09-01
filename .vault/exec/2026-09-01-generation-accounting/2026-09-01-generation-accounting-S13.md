---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:133b8161d9d2d73b0f17fbf646da394616dab39c41f4a1bdaffe46a1244e5f25'
step_id: 'S13'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Probe a resumed clean generation's explicit build collection when validating retained storage evidence

## Scope

- `src/vaultspec_rag/indexer/_generation_lifecycle.py`

## Description

- Resolve the generation's build collection before probing storage evidence.
- Probe that explicit private collection for clean generations and retain the served default for in-place generations.

## Changes

- Passed the lifecycle-derived build target to the storage existence probe.

## Outcome

Resuming a clean generation now rejects missing private build storage before retained
ledger work can be skipped or the partial replacement is published. The served collection
remains untouched until the existing publication transition.

## Notes

Focused static and unit gates passed. The integration regression is owned by the following
test step.
