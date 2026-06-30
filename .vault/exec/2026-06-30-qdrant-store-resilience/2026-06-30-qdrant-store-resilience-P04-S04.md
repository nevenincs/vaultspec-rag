---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-30-qdrant-store-resilience-plan]]"
---

# Add a server qdrant quarantine CLI verb that lists collections and quarantines a named one

## Scope

- `src/vaultspec_rag/cli/_service_qdrant.py`

## Description

Added the `server qdrant quarantine` operator escape-hatch verb.

## Outcome

No argument lists the store's collections; a named collection is quarantined under `--yes` (with `--dry-run` preview and a `--json` envelope); an unknown name exits non-zero. Shares the QR2 primitive (QR5).

## Notes

Tested via CliRunner: list, dry-run (no move), refuse-without-yes, quarantine-with-yes, unknown-collection exit 1. Live-smoke confirmed.
