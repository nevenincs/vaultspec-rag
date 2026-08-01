---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:6f78c12e41433724bef0a8b0094d185c7dcbb180ee62567ed00ff2a72218104f'
step_id: 'S106'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Render targets, extractor versions, path-independence, schema migration, and disabled execution through preprocess list, check, and status

## Scope

- `src/vaultspec_rag/cli/_preprocess.py`

## Description

- Render schema, targets, extractor versions, path-independence, and disabled execution in list, check, and status output.

## Outcome

Preprocessing CLI inspection now exposes the complete execution and migration contract in
human and JSON forms. List, check, run-one, and status preserve stable
`migration_required` and `admission_config_invalid` outcomes without traceback or empty
JSON output.

## Notes

The disabled mode retains routing while suppressing execution, matching index behavior.
Status remains a successful inspection command and reports invalid policy kind and detail
inside its structured data envelope.
