---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
body_hash: 'sha256:3327d9c3bf7c3460e4b3de750d7ca3a0d9834ab627eb3268250345e75e59a213'
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
