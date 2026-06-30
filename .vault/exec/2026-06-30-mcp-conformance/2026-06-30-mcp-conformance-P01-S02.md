---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Make the machine-global resolution authoritative and demote the per-status-directory service.json to a non-overriding hint

## Scope

- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

Made the machine-global resolution authoritative and demoted the per-status-directory `service.json` to a compatibility fallback.

## Outcome

`_default_service_port()` now consults `_machine_service_resolution()` first and returns its port when a live machine service resolves; the status-directory `service.json` is read only as a fallback when no machine service resolves (older daemons, or a deployment that does not write the pointer). A foreign or stale status-dir file can no longer outrank the live machine service, which was the frozen-singleton defect. Proven by `test_machine_resolution_outranks_a_foreign_status_dir` and `test_status_dir_is_the_fallback_when_no_machine_service`.

## Notes

The resolution is re-read per call (a cheap file read plus a side-effect-free lock probe), so a service that starts or restarts after a long-lived consumer began is still resolved.
