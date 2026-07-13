---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# `preprocess-sandbox` `P03` summary

All three Steps closed (S11-S13). Files touched:

- Modified: `src/vaultspec_rag/watcher.py`, `src/vaultspec_rag/jobs.py`, `src/vaultspec_rag/server/_routes.py`, and their unit tests

## Description

Fixed the three server-path defects that would otherwise leave hooks silently
ineffective or their failures invisible (ADR D9). S11 confirmed the watcher's
trust-gated change filter was already healed by the P01 trust removal (rules
resolve for any root) and added a regression guard. S12 threads
`preprocess_skipped` and `preprocess_failures` end-to-end into the job record
and the `/jobs` response so a client can see which files failed extraction. S13
adds a torch-free `/reindex` pre-flight block reporting config presence, rule
count, mode, and whether hooks will run. Verification: 141 unit tests pass; ruff
and basedpyright clean.
