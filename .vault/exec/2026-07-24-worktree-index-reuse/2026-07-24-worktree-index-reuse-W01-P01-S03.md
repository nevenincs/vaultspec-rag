---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S03'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# fold the measured numbers into the ADR consequences section and revert the prototype patch to a clean tree

## Scope

- `.vault/adr/2026-07-24-worktree-index-reuse-adr.md`
- `working tree`

## Description

Folded the measured outcome from S02 into the decision record's Consequences
section and confirmed no throwaway prototype code remains in the working tree.

## Outcome

- The decision record's Consequences section was updated to replace the
  estimate framing with the measured result: the flag-OFF from-scratch code
  rebuild baseline (311 s at the constrained profile/batch), and the honest
  finding that end-to-end reuse did not engage in the live service rebuild path
  (0% observed hit rate against an eligible byte-identical sibling donor),
  despite donor discovery and eligibility being verified correct in isolation.
  No fabricated speedup was recorded.
- Working tree is clean of throwaway prototype code: the encode-seam module
  carries only the production read-through seam (donor context resolution and
  verified vector adoption), and the throwaway env-flag prototype helper and
  its stats env knob are absent. The uncommitted feature code (the production
  donor-candidacy, store donor reads, seam read-through, telemetry, and tests)
  remains staged for the W03 landing steps and is intentionally not part of
  "clean tree" here, which concerns only the removal of the throwaway probe.

## Notes

- The measured headline is a baseline plus a blocking anomaly, not a speedup:
  the reuse feature must be made to actually engage in the live service rebuild
  path before the fork-speedup headline can be claimed (follow-up flagged in
  S02 and in the end-to-end validation record).
