---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S09'
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
     The S09 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The add a test asserting the config override raises the ceiling above the profile floor and still lowers it below and ## Scope

- `src/vaultspec_rag/tests/test_config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# add a test asserting the config override raises the ceiling above the profile floor and still lowers it below

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Added a test proving the override raises the effective ceiling ABOVE the
  profile figure and lowers it BELOW - the bidirectionality the old clamp
  could not express.
- Added a test exercising both auto-derive branches (device total present ->
  total minus headroom; absent -> profile fallback) by patching the probe.
- Updated the resilience matrix: `index_cuda_ceiling_mb` default is now 0 and
  it moves out of the reject-zero set; added the headroom knob to it; added an
  explicit accept-zero / reject-negative guard for the sentinel.

## Outcome

All 125 config tests pass.

## Notes

These are positive/contract tests of the resolution logic, not guard tests, so
green runs suffice. The cross-job and double-count GUARD proofs are P04 work in
phase P03/P04 and are not attempted here.
