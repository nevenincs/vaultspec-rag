---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S08'
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
     The S08 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Refuse a dense width, distance, or vector-name disagreement at the ensure step with a message naming expected and actual and ## Scope

- `src/vaultspec_rag/store.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Refuse a dense width, distance, or vector-name disagreement at the ensure step with a message naming expected and actual

## Scope

- `src/vaultspec_rag/store.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

`StorageGeometryError`, raised from `_verify_conformance` on and only on
`geometry_fatal`, naming both the expected and the actual width.

This moves a failure that was already fatal, not a new one. Previously the
disagreement surfaced at the upsert, where the write classifier does not treat
the rejection as unrecoverable, so the run spent its full retry and backoff
budget logging a transient store failure before raising; on the search side the
first line an operator saw blamed hybrid search while the dense fallback raised
uncaught. Refusing at ensure returns that budget and attributes the cause.

Because the raise happens before `_ensured` is set, a subsequent call re-probes
rather than caching a fatal - a store that is repaired underneath recovers
without a reopen.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
