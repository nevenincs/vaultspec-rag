---
tags:
  - '#plan'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
tier: L3
related:
  - '[[2026-07-24-worktree-index-reuse-research]]'
  - '[[2026-07-24-worktree-index-reuse-adr]]'
---

# `worktree-index-reuse` plan

## Wave `W01` - measure at the seam

Lock the decision-grade numbers with a flagged throwaway prototype at the encode seam before any production code: real fork wall-clock old vs new, reuse hit rate, and the unmeasured fresh-namespace upsert plus prealloc wall-time. Wave W02 depends on these numbers to size batching and candidate caps; authorized by the accepted ADR and the research spikes in related frontmatter.

### Phase `W01.P01` - flagged prototype spike

A roughly 100-line throwaway patch behind an env flag at the encode-seam caller measuring the headline numbers on a real fork of this repo into a scratch namespace.

- [x] `W01.P01.S01` - implement the throwaway env-flag-gated donor-lookup prototype at the encode-seam caller (retrieve-by-id from one named donor namespace, content verify, adopt vectors, encode misses); `src/vaultspec_rag/indexer/_streaming.py` (temporary patch, not for landing)\`.
- [x] `W01.P01.S02` - run a real fork index of this repo into a scratch namespace with the prototype off then on; `record old-vs-new wall-clock, reuse hit rate, and fresh-namespace upsert plus prealloc wall-time;`scratch namespace run; numbers into the Step Record\`.
- [x] `W01.P01.S03` - fold the measured numbers into the ADR consequences section and revert the prototype patch to a clean tree; `.vault/adr/2026-07-24-worktree-index-reuse-adr.md`; working tree\`.

## Wave `W02` - production read-through reuse

Build the production mechanism the ADR decides: donor-candidate selection from the storage manifest with the full eligibility gate, then the encode-seam read-through (retrieve-by-id, per-point content verify, vector adoption, miss encode) with the off-switch flag and telemetry counters. Depends on W01 numbers; Wave W03 verifies and ships it.

### Phase `W02.P02` - donor candidacy and eligibility

The read-only donor-candidate module: manifest-driven candidate discovery, the full eligibility gate (collection kind, dims and vector layout, embedding model identity including revision, content-epoch sentinel), sibling-first ranking, and the candidate cap.

- [x] `W02.P02.S04` - implement read-only donor-candidate discovery from the storage manifest with sibling-first ranking and a hard candidate cap; `src/vaultspec_rag/indexer/_donor_candidates.py` (new)\`.
- [x] `W02.P02.S05` - implement the donor eligibility gate: collection kind, dense dims and named-vector layout, embedding model identity including revision, and content-epoch sentinel equality; `src/vaultspec_rag/indexer/_donor_candidates.py`.
- [x] `W02.P02.S06` - add unit tests covering candidate discovery, ranking, the cap, and each eligibility gate rejecting an ineligible donor; `src/vaultspec_rag/tests/test_donor_candidates.py` (new)\`.

### Phase `W02.P03` - encode-seam read-through and telemetry

The production reuse mechanism at the single encode seam: batch retrieve-by-id with vectors outside the GPU lock, per-point payload-content verify, dense plus sparse vector adoption on hits, GPU encode of misses only, the default-on off-switch, and per-job telemetry counters.

- [x] `W02.P03.S07` - add the default-on reuse off-switch knob to config with env override, and thread it to the indexer entry points; `src/vaultspec_rag/config.py`; indexer wiring\`.
- [x] `W02.P03.S08` - implement the backend-aware batch retrieve-by-id-with-vectors donor read path in the store layer (server mode cross-namespace; ``` local mode same-process handles only); ``src/vaultspec_rag/store.py ```.
- [x] `W02.P03.S09` - implement the encode-seam read-through: per-point payload-content verify, dense plus sparse adoption on verified hits, GPU encode of misses only, every donor lookup outside the GPU lock on the existing consumer thread; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W02.P03.S10` - add per-job reuse telemetry (hit count, hit rate, GPU-seconds-saved estimate, donor-absent rate) surfaced through the existing job status envelope; `indexer job accounting; server jobs surface`.
- [x] `W02.P03.S11` - add unit tests for the read-through: verified hit adopts vectors and skips encode, miss encodes, flag off restores baseline behavior exactly; `src/vaultspec_rag/tests/test_index_reuse.py` (new)\`.

## Wave `W03` - prove, document, ship

Prove the eligibility gates with mutation-verified guard tests (each gate broken must turn its test red on the intended assertion, then green on restore, both directions recorded), run the full quality gates, capture end-to-end telemetry on a real fork, update user docs, and land the work committed and pushed. Terminal wave; depends on W02.

### Phase `W03.P04` - mutation-proven guard tests and gates

Guard tests for every eligibility gate proven able to fail by targeted mutation in one uninterrupted red-green sequence, plus the full lint, type, and test gates on the changed surface.

- [x] `W03.P04.S12` - prove the content-verify guard test can fail: mutate the verify to accept mismatched payload content, observe the intended assertion go red, restore, observe green; ``` record both directions in the Step Record; ``src/vaultspec_rag/tests/test_index_reuse.py ```.
- [x] `W03.P04.S13` - prove the dims and vector-layout gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded; `src/vaultspec_rag/tests/test_donor_candidates.py`.
- [x] `W03.P04.S14` - prove the embedding-model-identity gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded; `src/vaultspec_rag/tests/test_donor_candidates.py`.
- [x] `W03.P04.S15` - prove the content-epoch gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded; `src/vaultspec_rag/tests/test_donor_candidates.py`.
- [x] `W03.P04.S16` - run the full quality gates on the changed surface: ruff, formatting, type check with the project settings, complexity gate, and the affected pytest suites; `repository quality gates`.

### Phase `W03.P05` - end-to-end validation, docs, landing

Real-fork end-to-end telemetry capture with the flag on and off, user-facing documentation of the flag and telemetry, and the commit-and-push landing of the whole feature.

- [x] `W03.P05.S17` - run the end-to-end fork index with the flag on and off against a real sibling donor; `capture and record the telemetry and headline wall-clock in the Step Record;`live service run; Step Record\`.
- [x] `W03.P05.S18` - document the reuse behavior, the off-switch, and the telemetry fields in the user-facing docs; `docs/`.
- [x] `W03.P05.S19` - commit the feature with a why-focused message and push to origin main; `git`.
- [x] `W03.P05.S20` - fix or explicitly file the rebuild-replays-deleted-collections defect: storage delete leaves the resume ledger, so a rebuild replays committed vectors instead of rebuilding; ``` repro plus fix plus guard test, escalating if the ledger delete contract must change; ``src/vaultspec_rag/indexer/_run_checkpoint.py ```; storage delete surface; tests\`.

## Description

Execute the accepted decision in the related ADR: encode-seam read-through vector reuse by deterministic point id, so a new worktree fork reuses byte-identical vectors from sibling donor namespaces instead of recomputing every embedding on the GPU. Wave W01 locks the decision-grade numbers with a flagged throwaway prototype; Wave W02 builds the production donor-candidacy module and the seam read-through with off-switch and telemetry; Wave W03 proves the guards by mutation, validates end to end, documents, and lands. All steps are governed by the single ADR in the related frontmatter, grounded by the research document's spikes.

## Steps

## Parallelization

Waves are strictly sequential: W01 numbers gate W02 sizing decisions; W02 code gates W03 verification. Within W02, Phase P02 (donor candidacy) and the store-layer step of P03 can proceed in parallel since they touch disjoint modules; the seam step P03.S09 hard-depends on both P02 and the store read path S08. Within W03, the four guard-proof steps of P04 are mutually independent but each depends on its subject test landing in W02; P05 is sequential after P04.

## Verification

- The prototype run produced a recorded old-vs-new wall-clock pair, a hit rate, and the fresh-namespace upsert plus prealloc wall-time, folded into the ADR.
- A verified hit adopts donor dense and sparse vectors and performs zero forward passes for that point; a miss encodes exactly as before; the off-switch restores baseline behavior byte-for-byte (asserted by tests).
- Every eligibility-gate guard test has a recorded red-then-green mutation proof in its Step Record.
- No donor lookup executes while the GPU lock is held (asserted by test); chunk workers remain torch-free; no new on-disk state exists after a run.
- ruff, formatting, type check, complexity gate, and the affected pytest suites pass on the changed surface.
- The end-to-end fork run shows the headline speedup with telemetry recorded; docs updated; work committed and pushed to origin main.
- The plan is complete when every Step is closed.
