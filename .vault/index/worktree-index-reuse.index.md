---
generated: true
tags:
  - '#index'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-24-worktree-index-reuse-W01-P01-S01]]'
  - '[[2026-07-24-worktree-index-reuse-W01-P01-S02]]'
  - '[[2026-07-24-worktree-index-reuse-W01-P01-S03]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P02-S04]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P02-S05]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P02-S06]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P03-S07]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P03-S08]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P03-S09]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P03-S10]]'
  - '[[2026-07-24-worktree-index-reuse-W02-P03-S11]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P04-S12]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P04-S13]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P04-S14]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P04-S15]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P04-S16]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P05-S17]]'
  - '[[2026-07-24-worktree-index-reuse-W03-P05-S18]]'
  - '[[2026-07-24-worktree-index-reuse-adr]]'
  - '[[2026-07-24-worktree-index-reuse-plan]]'
  - '[[2026-07-24-worktree-index-reuse-research]]'
---

# `worktree-index-reuse` feature index

Auto-generated index of all documents tagged with `#worktree-index-reuse`.

## Documents

### adr

- `2026-07-24-worktree-index-reuse-adr` - `worktree-index-reuse` adr: `encode-seam read-through vector reuse by point id` | (**status:** `accepted`)

### exec

- `2026-07-24-worktree-index-reuse-W01-P01-S01` - implement the throwaway env-flag-gated donor-lookup prototype at the encode-seam caller (retrieve-by-id from one named donor namespace, content verify, adopt vectors, encode misses)
- `2026-07-24-worktree-index-reuse-W01-P01-S02` - run a real fork index of this repo into a scratch namespace with the prototype off then on
- `2026-07-24-worktree-index-reuse-W01-P01-S03` - fold the measured numbers into the ADR consequences section and revert the prototype patch to a clean tree
- `2026-07-24-worktree-index-reuse-W02-P02-S04` - implement read-only donor-candidate discovery from the storage manifest with sibling-first ranking and a hard candidate cap
- `2026-07-24-worktree-index-reuse-W02-P02-S05` - implement the donor eligibility gate: collection kind, dense dims and named-vector layout, embedding model identity including revision, and content-epoch sentinel equality
- `2026-07-24-worktree-index-reuse-W02-P02-S06` - add unit tests covering candidate discovery, ranking, the cap, and each eligibility gate rejecting an ineligible donor
- `2026-07-24-worktree-index-reuse-W02-P03-S07` - add the default-on reuse off-switch knob to config with env override, and thread it to the indexer entry points
- `2026-07-24-worktree-index-reuse-W02-P03-S08` - implement the backend-aware batch retrieve-by-id-with-vectors donor read path in the store layer (server mode cross-namespace
- `2026-07-24-worktree-index-reuse-W02-P03-S09` - implement the encode-seam read-through: per-point payload-content verify, dense plus sparse adoption on verified hits, GPU encode of misses only, every donor lookup outside the GPU lock on the existing consumer thread
- `2026-07-24-worktree-index-reuse-W02-P03-S10` - add per-job reuse telemetry (hit count, hit rate, GPU-seconds-saved estimate, donor-absent rate) surfaced through the existing job status envelope
- `2026-07-24-worktree-index-reuse-W02-P03-S11` - add unit tests for the read-through: verified hit adopts vectors and skips encode, miss encodes, flag off restores baseline behavior exactly
- `2026-07-24-worktree-index-reuse-W03-P04-S12` - prove the content-verify guard test can fail: mutate the verify to accept mismatched payload content, observe the intended assertion go red, restore, observe green
- `2026-07-24-worktree-index-reuse-W03-P04-S13` - prove the dims and vector-layout gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded
- `2026-07-24-worktree-index-reuse-W03-P04-S14` - prove the embedding-model-identity gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded
- `2026-07-24-worktree-index-reuse-W03-P04-S15` - prove the content-epoch gate guard test can fail by the same mutate-red-restore-green sequence, both directions recorded
- `2026-07-24-worktree-index-reuse-W03-P04-S16` - run the full quality gates on the changed surface: ruff, formatting, type check with the project settings, complexity gate, and the affected pytest suites
- `2026-07-24-worktree-index-reuse-W03-P05-S17` - run the end-to-end fork index with the flag on and off against a real sibling donor
- `2026-07-24-worktree-index-reuse-W03-P05-S18` - document the reuse behavior, the off-switch, and the telemetry fields in the user-facing docs

### plan

- `2026-07-24-worktree-index-reuse-plan` - `worktree-index-reuse` plan

### research

- `2026-07-24-worktree-index-reuse-research` - `worktree-index-reuse` research: `worktree fork index reuse`
