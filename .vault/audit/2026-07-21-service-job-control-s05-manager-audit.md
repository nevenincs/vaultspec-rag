---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:3abaeb2572cc0e980070880a43527adc6266feddf47c8163d4721bd95cd33b24'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `W01.P02.S05 bounded job manager`

## Scope

Independent safety, intent, concurrency, and compatibility review of the final
`W01.P02.S05` manager implementation in `jobs.py`.

## Findings

### root-alias-deduplication | high | Lexical aliases could admit duplicate active work

The initial implementation normalized path spelling without resolving filesystem identity.
A symlink, junction, or Windows extended-path alias could therefore acquire a second slot
for the same storage root. The revision strips extended prefixes, resolves the root, and
normalizes case before keying active work. Resolution failures now return the structured
`invalid_project_root` outcome.

### maintenance-paused-admission | high | Maintenance could occupy an unmanageable paused slot

The initial create path allowed `start_paused` for maintenance even though maintenance
capabilities are neither pausable nor resumable. The revision rejects that request with the
structured `invalid_start_state` outcome.

Final re-review found no remaining critical, high, medium, or low issues. Extended-path
deduplication, mode conflict, capacity, maintenance, idempotency, real threaded ownership,
and real asyncio ownership probes passed. Ruff, ty, BasedPyright, 49 focused tests, and diff
checks passed.

Status: **PASS** after revision. There are no unresolved critical or high findings.

## Recommendations

Keep later transition and persistence Steps within this manager authority and directly
verify exact serialization, race outcomes, and terminal immutability in the planned tests.
