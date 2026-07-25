---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S07'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

`evaluate_conformance` in the neutral schema leaf, returning a
`ConformanceVerdict` of `conforming`, `nonconforming`, or `unverifiable` plus a
`geometry_fatal` flag that separates the two failure modes sharing the
`nonconforming` verdict.

The version, width, and vector-name rules route through the existing
`assert_compatible` rather than being restated, so the two callers cannot drift.
The model comparison is this function's own, because it is the fact the
descriptor could never carry: `describe_storage_schema` reads the model from
live config, so it reports what the process is configured with and never what
built the vectors.

Built during `P01` as a consequence of placing `CollectionIdentity` in the same
leaf; closed here where the plan sequences it.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
