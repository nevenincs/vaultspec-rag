---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S06'
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
     The S06 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling and ## Scope

- `src/vaultspec_rag/job_dispatch.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling

## Scope

- `src/vaultspec_rag/job_dispatch.py`

## Description

- Replaced the one-way `min(profile, config)` clamp in `_admitted_resilience`
  (the pre-model admission snapshot) with `resolve_index_cuda_ceiling_mb`.

## Outcome

Admission now projects the derived or overridden ceiling. On the daemon torch
is resident, so the device query succeeds here too; off-GPU it falls back to
the profile figure.

## Notes

None.
