---
tags:
  - '#exec'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
step_id: 'S02'
related:
  - "[[2026-06-21-service-first-search-fallback-plan]]"
---

# Make routing service-first by dropping the silent auto-fallback and bare-search local path so a search without a mandate exits service-down

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Remove the silent `allow_fallback = True` auto-enable on service-port discovery.
- Gate the in-process search behind the mandate: a reachable service is used; a discovered-but-dead service with no mandate raises the port-unreachable error; no service and no mandate raises a new `_display_service_down_error`.

## Outcome

Bare search against a down or missing service now exits non-zero (service-first) and loads no local engine.

## Notes

A discovered-but-dead service no longer degrades to local; this is the core behavioural fix for the reported issue.
