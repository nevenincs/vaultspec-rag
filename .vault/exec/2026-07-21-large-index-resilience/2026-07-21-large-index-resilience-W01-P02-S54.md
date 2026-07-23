---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S54'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Treat a source file that reads as empty mid-save as a re-queued path rather than a job-level failure

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Add an empty-source admission reason and classify it as stable against the
  content that evidenced it (`src/vaultspec_rag/indexer/_content_policy.py:48`,
  `src/vaultspec_rag/indexer/_file_state.py:43`).
- Converge an empty source instead of raising, before the non-indexable
  classifier runs (`src/vaultspec_rag/indexer/_codebase_indexer.py:2299`).
- Identify an empty read exactly, from the digest the chunk worker already
  returned (`src/vaultspec_rag/indexer/_codebase_indexer.py:128`).
- Record the rejection through the checkpoint
  (`src/vaultspec_rag/indexer/_run_checkpoint.py:334`).
- Add a guard that an empty file does not fail a real index run
  (`src/vaultspec_rag/tests/integration/test_codebase_integration.py:889`).

## Outcome

A file with no content no longer fails the job it appears in. This was the
trigger for the cascade the rest of this phase repairs, so it is the entry to
that failure rather than another recovery from it.

The reclassification is the fix, not a re-queue. A file that reads as zero bytes
yields no chunks because there was nothing to chunk, which is not a chunking
defect and should never have been reported as one. Treating it as a failure let
a single editor save abort an entire indexing run, and because a failed run
leaves a resumable generation, that one transient race is what a later attempt
inherited.

The transient and genuine cases resolve structurally rather than by guessing
between them, which is what makes the loop the assignment warned about
impossible. The rejection is stable against the hash that evidenced it, joining
the two existing reasons that work that way. A file caught mid-save converges
against the empty hash; when the save lands its hash changes and it is
classified again under its real content and indexed normally. A genuinely empty
file keeps that hash and stays converged, so nothing re-triggers it. Neither
case retries, and neither needs the run to fail, so no distinction between them
has to be made at all.

Detection is exact rather than heuristic. The digest of a zero-byte file is a
fixed value, and the chunk worker already returns the digest of the same read
that produced the chunks, so an empty read is recognised by comparison against
that constant. Nothing re-reads a file that may still be mid-write, which would
have raced the very condition being detected.

The change is narrow by design. Only a result that is both empty-hashed and
chunkless takes the new path; a file with content that produces no chunks is
still a chunk failure and still fails, because that is a genuine defect and
silencing it would have been the wrong trade. The converged state means the run
completes, the remaining files index, and the empty path is recorded honestly
rather than disappearing.

## Notes

The guard was confirmed against the unfixed behaviour. With the new path
removed, the same test fails with the exact error that opened this incident -
an admitted code source producing no indexable chunks, raised as a job failure.
That the reproduction matches the original trigger character for character is
the strongest evidence available that this is the right entry point. The probe
was reverted from a backup and its absence verified.

The guard reads the recorded state through the ledger rather than through the
indexer, because the indexer does not expose its checkpoint. That is a slightly
indirect observation and it depends on the run being the latest code generation,
which holds in an isolated fixture but would not in a shared one.

Coverage is code-only, matching the change. The document indexer classifies its
own results separately and an empty document source is not addressed here.

An empty file is now reported as policy-rejected rather than indexed, which is
honest but does mean operator surfaces that count rejections will show entries
for legitimately empty files. That seemed better than the alternatives: it
cannot be recorded as indexed, since indexed state requires commit evidence that
an empty file cannot produce, and leaving it unconverged would keep every empty
file permanently unresolved.
