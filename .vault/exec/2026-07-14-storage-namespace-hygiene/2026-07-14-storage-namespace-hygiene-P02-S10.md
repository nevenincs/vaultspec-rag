---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:fdbc04a63ad91958f0aacb16f2bf635bb9ecf8e7d08c8cf9ea09e40e1ad14859'
step_id: 'S10'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Document delete --root harness-teardown recipe and the survey freshness semantics across docs/cli.md and docs/storage-maintenance.md

## Scope

- `docs/cli.md`

## Description

- Document the snapshot cache, `computed_at`/`source` metadata, eventual consistency, and `--fresh`/`?fresh=true` in `docs/storage-maintenance.md` and the `server storage survey` reference in `docs/cli.md`
- Document `--root` addressing, the `already_absent` idempotent success, and the harness-teardown recipe in both files; extend the delete exit-code table

## Outcome

The docs describe the shipped behavior of both phases, including the reply the dashboard team needs (HTTP stays read-only; `delete --root --json` is the sanctioned teardown). Commit 7ae79ca.

## Notes

None.
