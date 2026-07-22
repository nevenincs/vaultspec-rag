---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S93'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify watcher classification matches full and scoped discovery for ordinary real file events

## Scope

- `src/vaultspec_rag/tests/integration/test_watcher_content_admission.py`

## Description

- Emit ordinary real filesystem additions and modifications through the watcher filter.
- Compare watcher decisions with full and scoped production discovery.
- Cover conventional, ambiguous, explicitly routed, and ignored paths.

## Outcome

Ordinary watcher events agree with full and scoped discovery for the same active policy
snapshot and disposition vocabulary.

## Notes

Reconciled from production integration coverage in commit `3602ee9`.
