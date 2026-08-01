---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:e0353944f6cd5a1eaf656f69aab072426fbffc2bde6ff95527d3e1ea664c3f7b'
step_id: 'S19'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify a blocked store consumer cannot trap producer queue waits or hold the writer lock beyond the deadline

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Confirm a blocked store consumer cannot trap producer queue waits or hold the
  writer lock past the deadline, by running the verify test against clean
  committed HEAD on real CUDA
  (`src/vaultspec_rag/tests/integration/test_indexer_integration.py`).

## Outcome

The blocked-consumer verify passes on real CUDA against committed HEAD. When the
store consumer blocks, the producer's queue waits are not trapped and the index
writer lock is released at the no-progress deadline rather than held
indefinitely - so a wedged store cannot escalate into a permanently stuck
indexer. Run on the development GPU against a clean extract of HEAD, it passed.

## Notes

Confirmed against a clean extract of committed HEAD rather than the shared
working tree. This test lives in the same file another effort had modified with
uncommitted work, so the clean-archive run is the authoritative one; the
sibling ceiling step's record documents the contaminated first run and its
correction in full. This test itself passed in both, but the standard applied is
the clean-HEAD result.

The document-domain parity suite sharing this file is a separate inherited
feature, untouched here.
