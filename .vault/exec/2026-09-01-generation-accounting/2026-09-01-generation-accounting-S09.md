---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:18c37a646d0d6cbec9544b8f196f01a76aac3c577fd936ab3a76815637d16f01'
step_id: 'S09'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Preserve the explicit collection through code write and deletion table preparation

## Scope

- `src/vaultspec_rag/store_ingest.py`

## Description

- Resolve the code collection once, then pass that resolved target to table preparation for both upsert and deletion.
- Keep the existing target-scoped locks and point operations unchanged.

## Outcome

Explicit build collections are now created and prepared without creating or touching the served code collection.

## Notes

The focused GPU code-store test selection could not start because this host has no
pre-provisioned, manifest-verified Qdrant binary. The repository gate correctly
refused to run tests before collection; no unverified binary was installed.
