---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S26'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Run the full hardening gate across unit, integration, and adversarial suites

## Scope

- `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`

## Description

- Ran the full hardening gate: the 8 hardening test modules (detection, identity, supervise
  diagnostics, attach, orphan reap, machine singleton, adversarial singleton, adversarial
  multi-repo) together - 36 passed in ~38s on the real GPU.
- Ran the refactor regression checks: package import smoke (no `server`\<->`cli` cycle from the
  `_machine_lock` move + lifespan/CLI wiring) and the ADR regression suite (27 passed).

## Outcome

The hardening gate is green: every adversarial and component guarantee passes, with no lint or
type violations and no mocks/skips.

## Notes

The `test_service_lifecycle.py` server-mode daemon tests fast-fail in THIS local environment
because no qdrant binary is provisioned under the isolated test STATUS_DIR (the pre-existing
binary guard fires before any daemon spawns); root-caused as environmental, independent of the
hardening changes (binary resolution is untouched, and the failure precedes the machine-lock
acquire). Making those tests exercise the live daemon is tracked as `W04.P09.S29`. A leaked
identity sidecar at the real machine path (from an earlier `config_override` test iteration,
since fixed to the env knob) was cleaned; the isolation guard is tracked as `W04.P09.S31`.
