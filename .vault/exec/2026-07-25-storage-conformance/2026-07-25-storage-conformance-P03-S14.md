---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S14'
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
     The S14 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Report the per-collection verdict and stamped identity in the storage survey payload and ## Scope

- `src/vaultspec_rag/storage_survey.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Report the per-collection verdict and stamped identity in the storage survey payload

## Scope

- `src/vaultspec_rag/storage_survey.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

`NamespaceSurvey` gains a `models` map of collection name to stamped dense
model, populated from the manifest entry in `classify_namespaces` and carried
through the `/storage/survey` payload.

The field is defaulted rather than required. A second construction site surveys
a live server without a manifest read; defaulting lets it report nothing about
provenance instead of reporting a value it never looked up, and avoids editing a
file another team is concurrently changing.

An empty map means the namespace predates stamping. The survey has always been
able to say how much is stored; this is the first thing it can say about what
made it.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
