---
derived_from:
  - "audit:2026-07-14-storage-autoprune-safety-audit"
---

# Automated destruction requires time-confirmed danglingness

## Rule

Automated deletion of indexed data requires classification AND a persisted
continuous grace window - a single-scan "root path does not exist"
observation is never sufficient. Data-bearing namespaces additionally
require a recoverable archive to have succeeded before destruction, and
`unknown`/`unverifiable` namespaces are never auto-touched.

## Why

A valid root can transiently not-exist: an unplugged drive, an offline
share, a directory mid-rename, a worktree being re-created. The manual
prune has a human as the confirmation; the scheduled auto-prune
(`2026-07-14-storage-autoprune-safety-adr`) replaces that human with time -
`first_seen_orphaned` persists in the storage manifest across daemon
restarts, any live or unverifiable observation resets it to zero, so
protection can only ever be extended by races, never shortened. The
empty/data tier split matches the measured waste profile: the 167.9GB
reclaimed on 2026-07-13 was entirely zero-point namespaces.

## How

- **Good:** `evaluate_reclaim` in `src/vaultspec_rag/storage_ops.py` -
  orphaned-only input, per-tier grace windows (24h empty / 168h data),
  riskless-empty-first under a per-cycle cap; `archive_prefix` raises on
  any snapshot failure so `delete_prefix` is never reached for unarchived
  data; the empty tier re-counts points immediately before the drop.
- **Bad:** dropping a namespace because one survey said its root was
  missing; destroying a point-bearing namespace after a failed archive;
  resetting grace clocks on daemon restart; auto-deleting anything the
  manifest cannot attribute.
