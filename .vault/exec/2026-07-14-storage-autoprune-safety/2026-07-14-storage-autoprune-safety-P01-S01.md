---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:c343309e4874af92c2086ca40c73acbc1835333d4844f86e0cda91c6d2d11a81'
step_id: 'S01'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

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
