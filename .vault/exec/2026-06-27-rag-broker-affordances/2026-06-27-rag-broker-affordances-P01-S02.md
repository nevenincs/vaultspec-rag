---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Reorder service_start so the idempotent already-running check precedes the port and machine guards

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Moved the `_existing_service_running()` idempotent check to the TOP of `service_start`, ahead of the port and machine guards: a healthy owned service is now `already_running` (success) before the guards, instead of tripping the port-guard exit 1 first.
- Removed the now-redundant late `if _existing_service_running(): return`.

## Outcome

The friendly idempotent path is no longer shadowed: an already-running owned service exits 0, while the port and machine guards still catch the genuine "a foreign process holds the port" / "another service owns the machine" cases.

## Notes

The reorder is safe because the guards only need to catch NON-our-service conditions, which the idempotent check (identity + health) already excludes.
