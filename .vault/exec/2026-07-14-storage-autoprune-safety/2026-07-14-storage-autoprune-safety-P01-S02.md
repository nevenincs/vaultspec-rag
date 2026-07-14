---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S02'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Add grace-window evaluation and two-tier reclamation eligibility (empty orphans past grace_hours and point-bearing orphans past grace_hours_data) plus the per-collection snapshot-archive helper and the byte-capped, age-capped archive retention sweep and ## Scope

- `src/vaultspec_rag/storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add grace-window evaluation and two-tier reclamation eligibility (empty orphans past grace_hours and point-bearing orphans past grace_hours_data) plus the per-collection snapshot-archive helper and the byte-capped, age-capped archive retention sweep

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

- Add `ReclaimPolicy` (grace hours per tier, per-cycle cap, archive
  retention and byte cap) and `ReclaimDecision`.
- Add `evaluate_reclaim`: orphaned-only, stamped-grace gating per tier,
  empty namespaces ordered before point-bearing so the riskless tier
  reclaims first under a tight cap; over-cap prefixes are `deferred`.
- Add `archive_prefix`: per-collection server-side snapshot (`wait=True`)
  moved into the bounded archive dir; any failure raises so the caller
  refuses the subsequent drop.
- Add `sweep_archive`: age-based deletion then oldest-first eviction past
  the byte cap.
- Add `run_maintenance_cycle`: survey, `update_orphan_stamps`, evaluate,
  apply (data tier archives before dropping; all destruction through the
  shared `delete_prefix`), sweep, and roll up namespace counts, pending
  grace, and dangling bytes for the jobs registry and health line.

## Outcome

The reclamation engine is pure storage IO with the ADR's stacked safety
gates; all 56 existing storage/manifest unit and integration tests pass;
ruff, ruff format, and basedpyright clean.

## Notes

`archive_max_bytes` (default 20GB) implements the ADR's "capped by total
bytes" archive bound; the config knob lands in S03 as
`storage_autoprune_archive_max_gb`.
