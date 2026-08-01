---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:e53d300a058e2e4b9cfad1546fed43a2a3850c7661bccdb90d6b52029519b088'
step_id: 'S14'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Decompose store responsibilities and migrate all direct importers

## Scope

- `src/vaultspec_rag/store.py`

## Description

Extract the runtime, catalog, collection, donor-read, and ingestion concerns
from the former store module into concrete owners. Migrate all production and
test consumers directly, leaving no compatibility module or package re-export.

Correct stale prose and logging references so the source, the search guide,
and the integration assertion name the concrete current owner.

## Outcome

The former `store.py` facade is removed. `VaultStore` remains the stable
runtime contract while its cohesive collaborators own their direct behavior.
The import-boundary scan found no former-store import, 112 focused store and
MCP-isolation tests passed, and a real small corpus index encoded and stored
six code chunks successfully. The independent review found no high- or
critical-severity issue.

## Notes

The shared structural-duplicate guard remains red only for unrelated CLI,
index-policy, and search work. Explicit paths were used for this step's
checks; unrelated archive-plan whitespace was not altered.
