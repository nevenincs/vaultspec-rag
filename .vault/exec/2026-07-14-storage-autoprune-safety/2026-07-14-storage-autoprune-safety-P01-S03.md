---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S03'
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
     The S03 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
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
     The Add the storage_autoprune knobs (enabled, interval_minutes, grace_hours, grace_hours_data, archive_retention_days, max_per_cycle) following the existing env and config-file naming and ## Scope

- `src/vaultspec_rag/config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the storage_autoprune knobs (enabled, interval_minutes, grace_hours, grace_hours_data, archive_retention_days, max_per_cycle) following the existing env and config-file naming

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add seven `storage_autoprune*` knobs across the three config surfaces
  (`EnvVar` members, `_ENV_OVERRIDE_MAP`, `_RAG_DEFAULTS`): enabled (default
  on), interval 60 minutes, grace 24h (empty tier) and 168h (data tier),
  archive retention 30 days, archive cap 20GB, and max 16 reclaims per
  cycle. Type coercion (bool/int/float) rides the existing default-driven
  env parsing.

## Outcome

Knobs resolve through env and config file like every other setting; all 45
config unit tests pass; ruff, ruff format, and basedpyright clean.

## Notes

`storage_autoprune_archive_max_gb` is the one knob beyond the ADR's list,
implementing its "archive dir capped by total bytes" bound explicitly.
