---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:e122a7a76b99614eaaa636b2ea5bc6db9f4f79fc25d7054dcf89ebabfe8722de'
step_id: 'S02'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# run a real fork index of this repo into a scratch namespace with the prototype off then on

## Scope

- `record old-vs-new wall-clock`
- `reuse hit rate`
- `and fresh-namespace upsert plus prealloc wall-time`
- `scratch namespace run`
- `numbers into the Step Record`

## Description

Ran a real fork index measurement on a byte-near-identical worktree of this
repository (a fresh worktree checked out at the resident-service worktree's
committed HEAD, so its tracked bytes match the donor namespace's indexed
content). The scratch root was indexed through the running machine-singleton
service on port 8766, code domain only (the encode-dominant cost the decision
targets), with the reuse off-switch first forced off, then on. The host has a
single 16 GB GPU shared with the resident service, so both runs used the
`embedded-local` support profile and a code encode batch of 16 to keep peak
CUDA under the profile's device ceiling; both runs used the same profile and
batch so the comparison is internally consistent. The scratch namespace was
dropped and its resume ledger cleared before each measured run so every run was
a true from-scratch rebuild rather than a checkpoint replay.

## Outcome

Flag OFF (reuse disabled) - clean from-scratch code rebuild:

- Wall-clock (service job runtime): 311 s
- Committed units: 398 source files; ~1,988 code chunks
- Peak CUDA allocated: ~4.6-5.0 GB (full GPU encode of every chunk)
- Per-job reuse telemetry: absent (correct - the off-switch was honoured)

Flag ON (reuse enabled, default-on) - clean from-scratch code rebuild against a
present, eligible sibling donor:

- Wall-clock: ~311 s (no measurable improvement over the OFF baseline)
- Peak CUDA allocated: ~4.6 GB (full GPU encode - no vectors were adopted)
- Reuse hits / hit rate / GPU-seconds-saved: none recorded; the per-job reuse
  telemetry block was absent, i.e. an effective hit rate of 0%

The headline the decision anticipated (a fork index dropping from full-encode
time to chunk + lookup + upsert time) was NOT observed: end-to-end reuse did
not engage in the live service full-rebuild path. Because no run adopted
vectors, the one previously-unmeasured cost (fresh-namespace upsert plus
preallocation wall-time) could not be isolated as a low-encode floor; the
full-encode baseline is the only wall-clock captured.

Isolation of the cause (read-only, in-process, against the same live storage):

- Donor discovery finds the correct sibling donor collection for the scratch
  root (the resident service worktree's code collection), ranked first.
- Donor eligibility PASSES every gate for that sibling when evaluated with the
  scratch root's real content-epoch: the two roots' recorded code content
  epochs are byte-identical, dims and vector layout match, and the model
  identity matches.
- The reuse off-switch config resolves enabled in an environment identical to
  the daemon's (including the daemon marker), and the daemon process env was
  confirmed to carry the enable flag.

So the candidacy and eligibility machinery is correct in isolation and a
~100% hit rate is expected on this fork, yet the live service rebuild neither
adopted vectors nor emitted a telemetry block. This is a blocking end-to-end
defect in the service rebuild path, not a donor-selection or eligibility miss.

## Notes

- The measured baseline supersedes the throwaway-prototype measurement this
  phase originally scoped (see S01); the production off-switch flag is the
  cleaner A/B lever and was used here.
- Early runs that appeared fast (47-85 s) were checkpoint-ledger REPLAYS, not
  reuse: dropping the Qdrant collection leaves the local resume ledger intact,
  so a subsequent rebuild resumed and re-published committed vectors with zero
  GPU work and no donor consultation. Clearing the ledger (a code-domain clean)
  before each run removed this contamination; the honest from-scratch encode is
  311 s at batch 16.
- Reuse telemetry was absent (null) rather than a populated donor-absent block,
  which by the reuse resolver's own control flow should only occur when reuse
  is disabled at resolution time - yet config resolves enabled and the donor is
  eligible. The precise live-path cause was not isolated within the window
  (a read-only store probe against the live server blocked, and the daemon did
  not surface the resolver's debug decisions); it needs runtime instrumentation
  of the resolver inside the service rebuild path as a follow-up.
- Profile/batch overrides do not affect the reuse key: the code content epoch
  hashes only preprocess rules, html-strip, and the emitted-byte cap, none of
  which the overrides touch.
