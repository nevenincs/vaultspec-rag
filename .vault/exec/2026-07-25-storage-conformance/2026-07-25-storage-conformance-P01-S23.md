---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S23'
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
     The S23 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Add the local-mode identity sidecar under the per-root storage directory, and the backend-dispatching accessor pair every caller uses instead of either home and ## Scope

- `src/vaultspec_rag/storage_identity.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the local-mode identity sidecar under the per-root storage directory, and the backend-dispatching accessor pair every caller uses instead of either home

## Scope

- `src/vaultspec_rag/storage_identity.py`

## Description

Added the local-mode identity home and the backend-dispatching accessor pair.

This Step exists because of a correction found during execution: the manifest
hook that was to hold the identity runs in server mode only, so local mode - the
documented path for small and offline projects - would have had no record at all
and every local collection would have read as permanently `unverifiable`. The
authorizing decision was amended in place to state the two-home design before
this Step was written.

## Outcome

`storage_identity.py`: `load_identity` and `record_identity` dispatch on
backend, plus a per-root sidecar under the local storage directory written
atomically under a lock, merging rather than replacing.

Extending the manifest to cover local roots was the obvious alternative and was
rejected on safety. The survey classifies a namespace by matching manifest
entries against live server collections and reclamation acts on that verdict; a
local entry would match nothing and so would present as an unattributable
namespace to the one surface whose governing rule says it must never be handed
one. A conformance feature must not create a new class of namespace the
reclaimer cannot explain. A guard test asserts a local stamp writes no manifest
entry.

The module is a torch-free leaf - stdlib plus the schema definitions - so it
stays importable from a spawn worker's chain without pulling in CUDA. The store
imports it function-locally, which is what keeps the store, manifest, and
accessor free of an import cycle.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
