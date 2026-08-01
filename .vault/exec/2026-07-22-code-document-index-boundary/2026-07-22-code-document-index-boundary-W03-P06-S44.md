---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:3eccd96318ba346602ce43d776d663dfda36501433f0c991dd3b2990f500ea08'
step_id: 'S44'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Make batch extraction, subprocess output, timeout, no-progress, and cancellation bounded and interruptible

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`
- `src/vaultspec_rag/indexer/_run_policy.py`

## Description

- Poll subprocess execution through cancellation and timeout checkpoints.
- Terminate and join extractor children on every interrupted path.

## Outcome

Long-running extraction is bounded and cooperatively interruptible without leaving a child process behind.

## Notes

The real cancellation test verifies both prompt control delivery and child-process exit.
