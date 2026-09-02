---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:33bf4e9c2e0734d0dbe5d23b5f19dc7e72066ef431499ec5e589615aecac91e5'
step_id: 'S25'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# Declare and route the MPS test marker without changing CUDA lanes

## Scope

- `pyproject.toml`

## Description

- Implement the planned change through the canonical accelerator and platform surfaces.
- Preserve CUDA behavior while adding explicit Apple MPS behavior and CPU refusal.
- Verify the changed seam with focused tests, static analysis, and guard evidence where applicable.

## Outcome

Completed in the integrated working tree. Focused feature tests, repository static gates, and the formal audit carry the aggregate verification evidence.

## Notes

No step commit was created because the worktree already contained user-owned overlapping changes that must remain intact.
