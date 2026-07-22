---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S91'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify an on-disk configuration edit during real extraction cannot change the active operation fingerprint or publication identity

## Scope

- `src/vaultspec_rag/tests/integration/test_policy_snapshot.py`

## Description

- Run a real extractor that edits configuration after operation admission.
- Hold extraction at a filesystem barrier while the policy file changes.
- Verify active worker shaping and publication retain the entry snapshot identity.

## Outcome

An on-disk policy edit cannot split one operation across old admission and new execution or
publication semantics; the following operation alone observes the edit.

## Notes

Reconciled from production integration coverage in commit `95e9b05`.
