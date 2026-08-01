---
tags:
  - '#audit'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:bc43a560929a9bf03271712f6023c6024bafad2efa80a40d90c544074543e538'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# `maintainability-remediation` audit: `job manager split`

## Scope

The audited change replaces the flat `job_manager.py` module with concrete
owners for models, execution, records, progress, control, persistence, and
shared state. The review checked direct import migration, canonical ownership,
durable lifecycle behavior, quiesce-gate propagation, logging, and static
typing before closing plan step W01.P02.S04.

## Findings

### dynamic-state-protocol | medium | Runtime fallback hid missing attributes

`job_manager/state.py` initially defined a runtime `__getattr__` that returned
`None`, which would have hidden misspelled aggregate attributes and made
`hasattr` unreliable. The static-only protocol now provides the type checker
view while `JobManager.__getattr__` raises `AttributeError` at runtime. The new
`test_job_manager_rejects_unknown_attributes` regression covers the restored
contract.

### direct-owner-migration | low | No unresolved facade or state-owner issue

The review found no package-root re-export, compatibility alias, duplicate
registry, or split of durable state ownership. `JobManager` remains the one
aggregate coordinator; its concrete owners share the same lock and state.

## Recommendations

- Keep the static protocol runtime-free and add explicit state members when a
  future owner needs stronger type precision.
- Require a real lifecycle or quiesce regression whenever execution ownership
  moves between concrete job-manager modules.
