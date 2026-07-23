---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S04'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Investigate whether the Hugging Face and pinned-binary downloaders expose incremental byte callbacks, and record whether download-percentage bars are feasible

## Scope

- `src/vaultspec_rag/tests/quality/ab_report.md`

## Description

- Inspected the two startup downloaders for a forwardable incremental byte callback.

## Outcome

The pinned Qdrant binary download reads in fixed chunks and already tracks bytes written against a known Content-Length in `qdrant_runtime/_provision.py`, so a determinate provisioning download bar is FEASIBLE as a follow-on. The Hugging Face model-weight download happens inside `SentenceTransformer(...)` construction, which exposes no forwardable byte callback (its `show_progress_bar` flag is encode-only), so model-weight download percentages stay DEFERRED. This confirms the ADR gate: the current increment stops at the model-count milestone; download-percentage bars are a separate, downloader-specific follow-on.

## Notes

Investigation only; no code changed. Recorded here per the plan rather than in a source-tree report.
