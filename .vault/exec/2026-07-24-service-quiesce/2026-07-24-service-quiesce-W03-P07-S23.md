---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:d7d2ac9c7ce77f89f98f7274280a28f800157bed6cadba9a450b4c026e171301'
step_id: 'S23'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Pass quiesce transition and service-state payloads through the single service-client transport unchanged, including retryable recovery failure, without local GPU behavior

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

Retain the single import-light service-client transport as a transparent
pass-through for lifecycle and service-state payloads. Preserve every
service-owned retryable failure field without adding local lifecycle or GPU
behavior.

## Outcome

Satisfied by current transport behavior and the real loopback transport guard
added in `f7fd4bd5`. `_try_http_admin` returns the decoded service mapping
unchanged; the checked-in guard proves exact preservation of the retryable
quiesce envelope used by the CLI.

## Notes

No production transport edit was necessary because the canonical transport
already met the clarified contract. Acceptance is static; the loopback guard
and fresh-interpreter import boundary were not rerun here.
