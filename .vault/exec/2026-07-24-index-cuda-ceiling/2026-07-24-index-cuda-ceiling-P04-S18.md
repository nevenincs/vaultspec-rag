---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S18'
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
     The S18 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
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
     The run the full unit suite and the citation-gate lint over every changed file and ## Scope

- `src/vaultspec_rag/tests` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# run the full unit suite and the citation-gate lint over every changed file

## Scope

- `src/vaultspec_rag/tests`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Run the full unit suite (integration and benchmarks excluded): 2329 passed, 0 failed.
- Run `ruff check src tools` wholesale and `ty check`: clean over every file this phase touched.
- Run the citation-gate lint: clean, no development-record citations in any changed source file.

## Outcome

CPU-side gates are green on the phase's surface. The only remaining ruff/ty findings sit in a file a concurrent session holds dirty and uncommitted; they are that session's in-flight edits, not this phase's, and were left untouched.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

A pre-existing type-gate failure in the device-capacity fallback test (module-attribute reassignment the checker rejects even under an ignore comment) was converted to the fixture-based setattr pattern, restoring the type gate to green.
