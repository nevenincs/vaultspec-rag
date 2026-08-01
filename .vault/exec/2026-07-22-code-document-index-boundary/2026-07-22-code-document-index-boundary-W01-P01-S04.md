---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:4e188d6a3db3482d820c2eb1a9b6d2e38237958020f5829345839dbbc50d341c'
step_id: 'S04'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reject legacy targetless, unknown-target, and conflicting routing policies before mutable index resources are opened

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`
- `src/vaultspec_rag/indexer/_content_policy.py`
- `src/vaultspec_rag/_job_errors.py`

## Description

- Add stable migration and admission-configuration job error kinds.
- Raise migration refusal for legacy schemas and missing required ownership fields.
- Raise admission refusal for unknown targets and unsupported schemas.
- Reject duplicate route patterns that assign different content owners.
- Preserve typed policy errors through legacy text classification.
- Validate lint, typing, imports, and real fail-closed loading paths.

## Outcome

Routing and migration defects now stop policy loading with structured, operator-actionable
errors instead of degrading into absent rules or fallback admission.

## Notes

No incidents or data loss. Store/job entry-point gating remains scheduled for S88; this Step
provides the mutation-free loader refusal that those entry points consume.
