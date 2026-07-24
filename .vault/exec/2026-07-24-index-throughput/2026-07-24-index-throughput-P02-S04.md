---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# add ingest-barrier tests including the mutation proof: remove the barrier, the terminal-state-precedes-applied-points assertion goes red, restore green, both directions recorded

## Scope

- `src/vaultspec_rag/tests/` store/indexer suites`

## Description

Ingest-barrier guard tests (`tests/integration/test_ingest_barrier.py`, commit `c64e8217`) against the real pinned qdrant 1.18.2 server, GPU-free deterministic CPU model: the acknowledged-but-never-applied wrong-vector-name batch is caught only by the barrier count; a production vault rebuild with server-side point loss fails before metadata publish (terminal state never precedes applied points); the happy path publishes; local mode is inert. Mutation proof, one uninterrupted sequence: `apply_ingest_barrier` weakened to return before fence and count -> both guards failed on the intended assertion (`DID NOT RAISE IngestVerificationError` - the vault rebuild published metadata over an empty collection and the poisoned batch was accepted); weakening reverted -> five of five tests green. Both directions recorded in the test commit body. Post-rebase obligations: re-run this proof, and additionally prove the barrier COMPOSES with the writer-side queue (drain plus applied-verification, with the acknowledged-never-applies injection through the writer) - composition proof is a binding integration requirement, not covered by the individual proofs.

## Outcome

## Notes
