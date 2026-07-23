---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S23'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Revise the public discovery schema, ownership, degraded-state, and reconcile contract through vaultspec-documentation

## Scope

- `docs/service-discovery.md`

## Description

- Ground the contract in the shipped discovery code before writing: the typed resolution
  and its three states, the owner-authenticated pointer primitives, the canonical status
  composition, and the bounded reconcile flow.
- Rewrite `docs/service-discovery.md` from a single-file schema note into the full
  consumer-facing discovery contract: OS-lock authority, the two `service.json` views
  (machine pointer beside the lock, per-status-directory operator file), owner-only
  authenticated publication, the interface field table, the staleness contract, the
  `ready`/`absent`/`degraded` typed resolution with its degraded reason vocabulary, the
  canonical operator states with exit codes, and the non-destructive `server reconcile`
  outcomes.
- Cite every claim by `path:line` locator; introduce no vault, plan, or ADR identifiers
  into the user-facing prose.

## Outcome

Contract document reflects shipped behaviour, not intent. Every schema field, state,
reason, source, and exit code is grounded in a code locator and was confirmed present in
`serviceclient/_discovery.py`, `serviceclient/_status.py`, `_machine_lock.py`, and
`cli/_service_reconcile.py`. No `src/` logic changed; only `docs/service-discovery.md`
was authored.

## Notes

- ADR-vs-code discrepancy: ADR D3 names the foreign-pointer reason `pointer_foreign_pid`;
  the shipped constant is `pointer_foreign` (`serviceclient/_discovery.py:66`, echoed at
  `serviceclient/_status.py:158` and in `tests/test_http_admin_errors.py:350`). The doc
  follows the code. Recorded as a finding for the ADR owner.
- ADR D3 enumerates `absent`, `ready`, `pointer_missing`, `pointer_invalid`,
  `pointer_stale`, `pointer_foreign_pid` as "states". The code refines this into a
  two-layer model: three `state` values (`ready`/`absent`/`degraded`) with the
  `pointer_*` values as `reason` codes, plus an additional `probe_failed` reason not in
  the ADR list. The doc documents the shipped two-layer model.
- No `src/` edits; dormant-effort files were read, not written.
