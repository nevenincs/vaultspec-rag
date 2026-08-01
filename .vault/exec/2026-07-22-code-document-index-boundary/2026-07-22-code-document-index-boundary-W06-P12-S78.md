---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:1b19a598b1bbf118a5ff8fcbff5fd2da4184e64f481012684a6578022e509ef7'
step_id: 'S78'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Expose active source and document support profiles and their independent ceilings in service status

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Project the configured support profile through the jobs service domain.
- Expose independent code and document ceilings at the health boundary.
- Verify all declared dimensions through a real HTTP health request.

## Outcome

Service status now reports the active named profile and separate code and
document limits for source files, source bytes, extracted bytes, generated
chunks, weighted work, queue bytes, RSS, and CUDA memory.

## Notes

Scoped Ruff and Ty checks passed. The targeted health test passed against the
real Starlette route.
