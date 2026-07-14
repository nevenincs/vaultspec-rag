---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S01'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S01 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Add the first_seen_orphaned field to ManifestEntry with lenient load of pre-upgrade manifests, plus stamp/clear helpers that persist the grace clock across daemon restarts and reset it when a root reappears and ## Scope

- `src/vaultspec_rag/storage_manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the first_seen_orphaned field to ManifestEntry with lenient load of pre-upgrade manifests, plus stamp/clear helpers that persist the grace clock across daemon restarts and reset it when a root reappears

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

- Add `first_seen_orphaned` to `ManifestEntry` as the persisted grace clock
  (ISO-8601, empty when live/unverifiable), serialized by `_write_manifest`
  and parsed leniently so pre-upgrade manifests load with the field absent
  (first reclaim therefore no earlier than one grace window after upgrade).
- Add `update_orphan_stamps(statuses, now_iso=...)`: one atomic
  read-modify-write that stamps newly orphaned prefixes (preserving an
  existing stamp - the clock measures continuous orphan-hood across daemon
  restarts) and clears the stamp on any live/unverifiable observation, so a
  reappearing root restarts its window from zero. Caller supplies the clock
  per the module's no-clock-dependency convention.

## Outcome

Manifest schema and grace bookkeeping in place; all 20 existing manifest
tests pass unchanged; ruff, ruff format, and basedpyright clean.

## Notes

None.
