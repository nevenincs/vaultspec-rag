---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S17'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# run the end-to-end fork index with the flag on and off against a real sibling donor

## Scope

- `capture and record the telemetry and headline wall-clock in the Step Record`
- `live service run`
- `Step Record`

## Description

- Provisioned a byte-near-identical fork: a fresh worktree of this repository
  checked out at the resident service worktree's committed HEAD, so its tracked
  bytes match the donor namespace's indexed content.
- Ran the live service (machine-singleton, port 8766, from the resident venv)
  code index of the fork with the reuse off-switch forced off, then on,
  clearing the scratch namespace and its resume ledger before each run.
- Captured per-job telemetry and wall-clock; cross-checked donor discovery and
  eligibility read-only in-process against the same live storage.
- Restored the service to default config and removed the scratch fork.

## Outcome

- Flag OFF baseline (clean from-scratch code rebuild, constrained profile and
  batch to fit the shared 16 GB GPU): 311 s wall, ~1,988 code chunks, ~4.6-5.0
  GB peak CUDA; reuse telemetry correctly absent.
- Flag ON (default-on, present eligible sibling donor): ~311 s wall, ~4.6 GB
  peak CUDA (full GPU encode), no reuse hits and no telemetry block - an
  effective 0% hit rate. The anticipated fork speedup was NOT observed.
- End-to-end reuse did not engage in the live service full-rebuild path. Because
  no run adopted vectors, the upsert-plus-preallocation floor could not be
  isolated below the full-encode cost.
- Isolation (read-only, in-process): donor discovery selects the correct
  sibling donor, eligibility passes every gate with the fork's real
  content-epoch (the two roots' code content epochs are byte-identical), and the
  reuse flag resolves enabled in a daemon-identical environment. The mechanism
  is correct in isolation and a ~100% hit rate is expected on this fork, so the
  gap is a live service-path defect, not a donor-selection or eligibility miss.

## Notes

- BLOCKING ANOMALY (needs follow-up before this step can close as a success):
  the live service rebuild emitted a null reuse telemetry block, which by the
  resolver's own control flow should occur only when reuse is disabled at
  resolution time - yet the flag resolves enabled and the donor is eligible.
  The precise cause was not isolated within the maintenance window: a read-only
  store probe against the live Qdrant server blocked (lock contention with the
  resident service), and raising the daemon log level did not surface the
  resolver's per-candidate debug decisions. A runtime trace of donor resolution
  inside the service full-rebuild path is the recommended next diagnostic.
- Measurement hazard recorded for the next runner: dropping a scratch namespace
  (Qdrant collection) leaves the local resume ledger intact, so a subsequent
  rebuild resumes and replays committed vectors with zero GPU work and no donor
  consultation - which looks like a fast reuse run but is not. Clear the resume
  ledger (a code-domain clean) before each measured run; the honest from-scratch
  encode is 311 s at the constrained batch, not the 47-85 s replays.
- Downstream steps (documentation and the commit/push landing) are premature
  until the live-path reuse defect is resolved.
