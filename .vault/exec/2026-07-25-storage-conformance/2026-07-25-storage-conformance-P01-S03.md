---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S03'
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
     The S03 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Stamp the effective dense model, sparse model, dense width, distance, vector names, and schema generation when a collection is created and ## Scope

- `src/vaultspec_rag/store.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Stamp the effective dense model, sparse model, dense width, distance, vector names, and schema generation when a collection is created

## Scope

- `src/vaultspec_rag/store.py`

## Description

Stamped the identity at collection creation, inside the lifecycle lock and
immediately after `create_collection` returns, so no other thread in the process
observes the collection before its provenance is recorded.

The width recorded is `self._embedding_dim` - the value the collection was
actually created with - not the config-derived width. The store can be
constructed with an override, and a stamp that recorded config instead would
describe a collection nobody built. This was corrected during the step after
first writing it against `current_identity()` unmodified.

## Outcome

`_stamp_identity` on the store, called from `_ensure_collection` after the
create. Dispatches on `_server_mode` and passes the local storage directory only
in local mode. Best-effort by construction: a stamp failure degrades a later
verdict to `unverifiable` and must never fail the index run that was creating
the collection.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
