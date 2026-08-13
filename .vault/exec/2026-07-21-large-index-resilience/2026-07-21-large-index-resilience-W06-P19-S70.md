---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:509902af2d3da17b097e321b2e81aff157ada6276a95ad443124057414d0ac38'
step_id: 'S70'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Raise ledger fixtures to a size that reaches the contention window, reusing the canonical corpus fixtures

## Scope

- `src/vaultspec_rag/tests/corpus.py`

## Description

- Give the contention tests a ledger seeded to a size where scanning it is real work.
- Reuse the suite's existing signature and unit construction helpers rather than adding parallel ones.

## Outcome

Fixture size is now part of what the tests assert, because contention only has a window while a reader holds its lock across something and a ledger of three rows cannot express the condition.

An earlier attempt extracted the shared helpers into a separate fixture module and renamed them at every call site. That was reverted: the public names collided with local variables in the existing tests, producing shadowing. Reusing the helpers where they already live achieves the same non-duplication without the churn.

## Notes

An attempt to extract the shared construction helpers into a separate fixture module was reverted. Renaming them to public names collided with local variables of the same name in the existing tests and produced shadowing; reusing the helpers where they already live achieves the same non-duplication without the churn.
