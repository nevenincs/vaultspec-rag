---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:0ed49405718027ee4d2d0f0082208238aacf4a38d9b9ef00bae51871a7fcae24'
step_id: 'S02'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Add canonical retirement for resumed retained outcomes with storage confirmation before ledger mutation

## Scope

- `src/vaultspec_rag/indexer/_drift_owner.py`

## Description

- Bind the drift owner to the lifecycle-derived active collection and route every drift delete through that target.
- Add one storage-first retained-outcome retirement operation that durably records deletion before withdrawing current-generation upsert evidence.
- Route vanished outcomes through path retirement and skipped outcomes through stale retirement before their replacement state is recorded.
- Add the bounded ledger evidence query and checkpoint projection required to replay an interruption between storage and ledger work.
- Update direct drift-owner callers for the required collection argument.

## Outcome

Resumed paths with current-generation upserts now remove only their ledger-recorded IDs from the active target before their old evidence is retired. Vanished paths leave the manifest through a confirmed path deletion; skipped paths retain their policy outcome after the old upserts are withdrawn. Unevidenced paths retain their previous convergence behavior.

Focused formatting, lint, strict type checking, and the existing run-checkpoint suite pass. The dedicated skip-and-vanish regression cases remain owned by S05.

## Notes

No data-loss incident occurred. The replayable evidence lookup reads durable upsert units rather than transient file state, so a restart after storage confirmation continues the same retirement.
