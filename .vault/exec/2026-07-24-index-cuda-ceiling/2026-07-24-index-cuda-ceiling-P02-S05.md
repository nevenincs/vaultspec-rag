---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S05'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-cuda-ceiling with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction and ## Scope

- `src/vaultspec_rag/memory_probe.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Added `resolve_index_cuda_ceiling_mb()`: a positive `configured_mb` is an
  authoritative bidirectional override; otherwise the ceiling is
  `device_total - headroom_mb`, falling back to the profile figure when the
  device total is unavailable.
- Added the `index_cuda_headroom_mb` default (2048) and its env var, and
  changed `index_cuda_ceiling_mb`'s default to `0` (auto-derive sentinel).
- Added `_finite_non_negative` so the ceiling knob admits its `0` sentinel.

## Outcome

The knob resolves 0 by default (auto) and honours a positive override; the
headroom knob resolves 2048 and rejects zero as before.

## Notes

The `index_cuda_ceiling_mb` knob changes meaning from an absolute cap to a
bidirectional override with a 0=auto sentinel. This is the operator-facing
semantic migration the ADR flagged for the changelog.
