---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Add bounded nonterminal admission and cooperative shutdown timing settings using vaultspec-standard-executor and ## Scope

- `src/vaultspec_rag/config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add bounded nonterminal admission and cooperative shutdown timing settings using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add a positive 64-job admission bound for exact-addressable nonterminal work.
- Add a finite positive 300-second cooperative shutdown window.
- Map both settings through the canonical environment-variable registry and RAG defaults.
- Validate resolved values before downstream lifecycle components consume them.

## Outcome

The service configuration now exposes `job_max_nonterminal` and
`job_shutdown_timeout_seconds` with bounded defaults, canonical environment mappings, and
fail-fast validation. Imported production probes confirmed defaults, environment coercion,
and invalid-value rejection. Ruff formatting and lint, ty, and BasedPyright passed.

## Notes

Job-manager admission, shutdown orchestration, and production-behavior tests remain assigned
to later plan Steps. No data was changed and no scaffold remains in production code.
