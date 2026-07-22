---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S30'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Invalidate incompatible checkpoints on model, schema, content, membership, preprocessing, and configuration drift

## Scope

- `src/vaultspec_rag/tests/test_config_epoch.py`

## Description

- Exercise the canonical generation signature against model, dimension, embedding-schema, payload-schema, content-epoch, membership-epoch, preprocessing, and pipeline-configuration drift.
- Require each incompatible signature to create a distinct generation and invalidate the prior active attempt before reuse.
- Retain the existing content and membership escalation matrix over real resolved policy snapshots.

## Outcome

Checkpoint reuse now has a closed verification matrix across every content- or storage-shaping identity required by the accepted compatibility contract. No incompatible attempt can authorize skipped work.

## Notes

The complete config-epoch and signature suite passed 31 tests. Ruff and ty passed for the changed test module.
