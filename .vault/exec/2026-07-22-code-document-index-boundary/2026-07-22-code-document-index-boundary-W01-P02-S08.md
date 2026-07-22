---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S08'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Separate conventional source admission from the parser and chunker capability registry

## Scope

- `src/vaultspec_rag/indexer/_chunking.py`
- `src/vaultspec_rag/indexer/_content_policy.py`

## Description

- Verify the parser capability registry remains complete for explicitly admitted content.
- Verify the conventional source profile uses its own narrower extension vocabulary.
- Verify parser selection occurs only after the shared classifier admits a path.

## Outcome

Default code membership is independent from parser availability. Ambiguous text and schema
formats require explicit caller routing while explicitly admitted content still receives the
available parser or generic text fallback.

## Notes

Reconciled from production commit `b4145fc`; no additional code change was required.
