---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S04'
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
     The S04 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Preserve a stored schema generation and identity when recording a root instead of overwriting them with current values and ## Scope

- `src/vaultspec_rag/storage_manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Preserve a stored schema generation and identity when recording a root instead of overwriting them with current values

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

Stopped the manifest relabelling itself. Recording a root now preserves the
stored schema generation and per-collection identity instead of overwriting them
with current values, and only a create restamps. A rekey carries the source
entry's generation and identity across the move for the same reason: a migrate
relocates data without rebuilding it, so restamping there would let a stale
namespace launder itself into a conforming-looking one.

The entry is now constructed inside the lock, after the existing record is
loaded, because it cannot be built until the value it inherits is known.

Also propagated identity through the two orphan-stamp rebuild sites, which
reconstruct the entry to move the grace clock and would otherwise have dropped
it. The grace clock's own reset semantics were left untouched - a live
observation clearing `first_seen_orphaned` only ever extends protection.

## Outcome

`record_root` and `rekey_prefix` preserve; `record_collection_identity` is the
only writer that stamps a current generation, and it is reachable only from a
create.

One consequence worth recording: `storage_schema_version` was dropped from
`record_root`'s idempotence comparison, since the entry now inherits it and the
comparison would always hold. That removal is what made the first version of the
S05 guard inert - see that Step's record.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
