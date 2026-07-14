---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S12'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Document the canonical receipt-carrying tool install command with the upgrade contract, the --with wheel-URL fallback, and the ephemeral-env trap including stop-the-service-before-forced-reinstall

## Scope

- `README.md`

## Description

- README quickstart gains the standalone-tool install with the cu130 --index (receipt-carried, upgrade-surviving) and links the installation guide.
- `docs/installation.md` documents the receipt mechanics, the in-place uv pip escape hatch (with its undone-by-next-upgrade caveat), the stop-the-service-before-forced-reinstall warning, and the uvx archive-v0 ephemeral fallback.

## Outcome

Committed as 0616f5f. mdformat clean.

## Notes

Scope grew from README.md to also cover docs/installation.md - the README quickstart links there and the detailed caveats belong in the installation guide, not the quickstart.
