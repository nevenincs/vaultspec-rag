---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Resolve console interactivity once, from the real stdout stream

## Scope

- `src/vaultspec_rag/cli/_core.py`

## Description

- Derive the shared console's interactivity from the real stdout stream instead of forcing it off.
- Funnel console construction through one site so the decision has a single home.
- Rewrite the surrounding comment: the CI variable it defended against is no longer set, and its claim that status messages still printed once was false.

## Outcome

One interactivity answer now governs every consumer. Measured on the pinned Rich version with identical code: 0 bytes rendered under the old construction, 159 under the new. The same change revives the search spinner, the warmup spinner, and the indexer progress bars, which were failing for this one reason.

## Notes

The bars were gated separately on terminal detection rather than interactivity, so that second answer was collapsed onto this one. Piped and captured output stays byte-identical to before, which is what the stream-derived value buys over terminal detection.
