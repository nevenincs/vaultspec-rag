---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---




# `index-backpressure-storage-hygiene` `P06` summary


## Description

Docs and closeout. Storage guide covers the ephemeral tier, debris
prune, and totals; configuration gains the TTL knob row; service-mode
documents the failure taxonomy, stall flag, and interrupted restore. Two
new ADR guards: the taxonomy import graph stays torch- and CLI-free, and
every CUDA-OOM handler keeps its floor raise.

- Modified: `docs/storage-maintenance.md`, `docs/configuration.md`,
  `docs/service-mode.md`,
  `src/vaultspec_rag/tests/test_adr_regression.py`

Verification: ADR regression suite green (32); markdown gates via CI.
