---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-27'
body_hash: 'sha256:e27cde9747b5943360f5f4161222aff89d549eba8686c2c2e86b6857e2ac9583'
step_id: 'S04'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# add ingest-barrier tests including the mutation proof: remove the barrier, the terminal-state-precedes-applied-points assertion goes red, restore green, both directions recorded

## Scope

- `src/vaultspec_rag/tests/` store/indexer suites\`

## Description

Ingest-barrier guard tests (`tests/integration/test_ingest_barrier.py`, commit `c64e8217`) against the real pinned qdrant 1.18.2 server, GPU-free deterministic CPU model: the acknowledged-but-never-applied wrong-vector-name batch is caught only by the barrier count; a production vault rebuild with server-side point loss fails before metadata publish (terminal state never precedes applied points); the happy path publishes; local mode is inert. Mutation proof, one uninterrupted sequence: `apply_ingest_barrier` weakened to return before fence and count -> both guards failed on the intended assertion (`DID NOT RAISE IngestVerificationError` - the vault rebuild published metadata over an empty collection and the poisoned batch was accepted); weakening reverted -> five of five tests green. Both directions recorded in the test commit body. Post-rebase obligations: re-run this proof, and additionally prove the barrier COMPOSES with the writer-side queue (drain plus applied-verification, with the acknowledged-never-applies injection through the writer) - composition proof is a binding integration requirement, not covered by the individual proofs.

## Outcome

Post-merge addendum: both post-rebase obligations are discharged on the merged main tree. (1) The barrier proof was re-run as one uninterrupted sequence - `apply_ingest_barrier` weakened to return before fence and count turned both guards red on `DID NOT RAISE IngestVerificationError`; restored, 5/5 green, working tree byte-identical. (2) The binding composition proof landed as `TestBarrierComposesWithSliceWriter` (commit `60f0e11b`): the acknowledged-never-applies injection goes THROUGH the slice writer during a production rebuild, the run fails at the barrier before stale-purge and metadata publish, and neutralizing the barrier's count comparison was observed red on the missing rejection before restore to 6/6 green.

## Notes

Template evidence: intro_commit=d81c21c6f44aed3da9929714232da41e21367d60; template_commit=d81c21c6f44aed3da9929714232da41e21367d60:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
