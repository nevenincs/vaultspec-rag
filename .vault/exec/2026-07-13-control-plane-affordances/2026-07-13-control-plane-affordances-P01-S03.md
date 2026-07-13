---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S03'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace control-plane-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S03 and 2026-07-13-control-plane-affordances-plan placeholders are machine-filled by
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
     The Add --root to server storage survey, pass it through both the service-first and CLI-direct paths, and render queried_root in human and --json output and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add --root to server storage survey, pass it through both the service-first and CLI-direct paths, and render queried_root in human and --json output

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add `--root` to `server storage survey`; the service-first path forwards it
  as the route's `root` query parameter and parses the returned
  `queried_root`.
- On the CLI-direct fallback (no daemon answering), resolve the root through
  the same `root_collection_prefix` derivation in-process and narrow the
  gathered namespaces to its prefix - one derivation, two execution homes.
- Render `queried_root` as a leading line in human output and as a `data`
  field in `--json` output (`_emit_survey_json` gained the optional
  parameter).
- Rename the parse-loop local to `entry_root` to avoid shadowing the new
  function parameter (caught by basedpyright).

## Outcome

`server storage survey --root <path>` reports the authoritative prefix and
the root's namespaces in both output modes and both execution paths. Ruff,
ruff format, and basedpyright clean.

## Notes

None.
