---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8128531e86f6da459d2ded771e188141e033b9c214b47f77220ce016ce63b0a8'
step_id: 'S14'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify full, scoped, API, CLI, and service admission parity against one real temporary repository

## Scope

- `src/vaultspec_rag/tests/integration/test_content_admission.py`

## Description

- Build a real temporary project with conventional, ambiguous, and explicitly routed files.
- Compare full and scoped discovery with API, CLI, and resident-service projections.
- Assert stable ownership, disposition reasons, counts, samples, paths, and policy identity.

## Outcome

Every public code-discovery surface consumes the same production admission decision over the
same real project fixture.

## Notes

Reconciled from production integration coverage. Verification is consolidated at the phase
boundary after the remaining production step.
