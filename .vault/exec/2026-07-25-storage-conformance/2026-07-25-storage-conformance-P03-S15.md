---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S15'
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
     The S15 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Render the survey verdict and stamped models in the storage CLI view and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Render the survey verdict and stamped models in the storage CLI view

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

The storage CLI carries `models` in its JSON, and in the human view names a
namespace whose collections disagree with each other plus a count of namespaces
that predate stamping.

Deliberately bounded, per the operator-views rule. A per-namespace model line
would add noise to every row to state the expected case; only a namespace
holding more than one distinct model gets a line, because collections under one
root disagreeing about what built them is the state worth attention. The
unstamped count is a single trailing line rather than a marker per row.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
