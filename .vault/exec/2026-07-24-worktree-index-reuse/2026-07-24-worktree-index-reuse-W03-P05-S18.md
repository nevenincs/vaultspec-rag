---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:248880df524703133e5612de9e0567706b007d8ad2f00a4421f4ccd4ee2dff2d'
step_id: 'S18'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# document the reuse behavior, the off-switch, and the telemetry fields in the user-facing docs

## Scope

- `docs/`

## Description

- Studied the existing `docs/` structure, voice, heading style, and table
  conventions across the indexing, configuration, and service-mode pages.
- Added a `Reusing vectors across worktrees` subsection to the indexing internals
  page covering the benefit (near-instant worktree forks), when reuse applies
  (same machine, sibling already-indexed roots, exact content), the safety story
  (exact point-id plus byte-for-byte content verification through the eligibility
  gates, never similarity-based; misses encode as before), and the off-switch.
- Added the `VAULTSPEC_RAG_INDEX_REUSE` knob to the indexing page's
  configuration-knobs table and to the configuration reference's Indexing table.
- Documented the `reuse` telemetry block on the job record in the service-mode
  observe-activity section, explaining `reuse_hits`, `reuse_misses`, `hit_rate`,
  `gpu_seconds_saved`, `donor_collections`, and `donor_absent`, and cross-linked
  it with the indexing subsection.

## Outcome

- Touched files: `docs/indexing.md`, `docs/configuration.md`,
  `docs/service-mode.md`.
- No unmeasured numeric performance claims were added; benefit is stated as
  orders-of-magnitude for near-identical forks.
- No development-record identifiers appear in the docs; behaviour is stated as a
  constraint the reader can act on.
- Both markdown gates pass on the touched files: `mdformat --check` (exit 0) and
  `pymarkdown` (exit 0).

## Notes

- Field and knob names were verified against the source (`config.py` off-switch
  mapping and the `reuse` snapshot on the job record) rather than taken from the
  task text alone.
