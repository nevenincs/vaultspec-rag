---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2309700939784309fedf887607eb982dbebe13e152157d09018f1c78d20d5272'
step_id: 'S43'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify profile requirements, corpus limits, disk preflight, checkpoint preservation, and structured refusal

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Verify independent named profiles and every admission dimension.
- Verify discovery counts only admitted code source files and bytes.
- Verify generated-weight refusal occurs before an overweight segment is yielded.
- Verify HTTP refusal is structured and precedes durable job creation.
- Re-run real CUDA and Qdrant checkpoint-preservation boundaries.

## Outcome

The support-profile boundary is covered from immutable measurement through service refusal and resumable storage. Over-budget work is typed, no refused job is persisted, and confirmed checkpoint work survives control and clean-rebuild resume.

## Notes

The phase boundary passed 10 cases in 28.51 seconds, including real CUDA and Qdrant execution. Ruff, formatting, and static type checks passed. The repository-wide complexity hook still reports its broad pre-existing baseline offenders; no new failing assertion or type finding remained in this block.
