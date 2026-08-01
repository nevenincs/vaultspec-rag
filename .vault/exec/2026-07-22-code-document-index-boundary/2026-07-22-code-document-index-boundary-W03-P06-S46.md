---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:ca289042dd865e08c8234447c310d21556b46456ff823e7410cbec9ac5155d14'
step_id: 'S46'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify failure visibility, decoder isolation, retry behavior, resource ceilings, and zero extractor launches for code-only jobs

## Scope

- `src/vaultspec_rag/tests/integration/test_document_execution.py`
- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

- Exercise decoder isolation, source refusal, kind-safe passthrough, cancellation, retry isolation, weighted queues, and failed metadata.
- Exercise document full and scoped incremental publication against real embedding and vector storage components.

## Outcome

The phase boundary passed twelve focused real-behavior tests with no fake, mock, patch, skip, or expected-failure shortcut.

## Notes

The test set includes zero-launch and no-orphan-process assertions.
