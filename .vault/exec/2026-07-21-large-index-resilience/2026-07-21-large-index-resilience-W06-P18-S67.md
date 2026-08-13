---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:0a2cc97ff1222900c77f883bef64dd4d47d4a0e8c7d522391bda133c400e52bd'
step_id: 'S67'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Prove a document or vault run opening the shared ledger cannot fail a concurrent code run's commit on the same root

## Scope

- `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`

## Description

- Assert that a held read over the shared file blocks neither content kind: code commits proceed, a document generation starts, and a document unit commits.
- Confirm the code generation remains the latest for its kind afterwards.

## Outcome

Covers the cross-kind claim the shared file makes: one root, one ledger, three content kinds, and no starving between them. Verified to fail without write-ahead logging and pass with it.

The first version of this test was discarded rather than kept. It looped a reopen-and-read on another kind while the code side committed, and it passed against the deliberately broken build - once the scan came off the open path there was no longer a long enough read to contend with. A guard that cannot fail is worse than no guard, so it was rewritten around a deterministically held read.

## Notes

The first version of this test passed against the deliberately broken build and was therefore worthless as a guard. Rather than keep a test that could not fail, it was rewritten around a deterministically held read. The discarded version relied on repeated reopens being slow, which stopped being true once the scan came off the open path.
