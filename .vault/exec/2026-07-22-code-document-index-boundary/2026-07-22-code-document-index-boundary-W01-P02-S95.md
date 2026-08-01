---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:1e6a1297c1aaed918c38f967d255ce4d48aeef87be7edf6b62f8ae410a3fda9e'
step_id: 'S95'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify the preprocessing kill switch suppresses real extractor execution while preserving ownership and stored points

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Seed a stored code point through a real configured extractor.
- Disable preprocessing, change the owned binary source, and run scoped reconciliation.
- Verify routing ownership remains explicit while extractor execution is suppressed.
- Verify stored IDs, metadata bytes, and cache contents remain unchanged and stale work is reported.

## Outcome

The real-behavior integration test proves that disabling preprocessing suppresses hook
execution without reclassifying owned content or deleting its published state.

## Notes

The first phase-boundary run exposed the newly required immutable preflight argument in the
test call. After passing the resolved full and scoped preflights, the consolidated boundary
suite passed 4 tests with no failures.
