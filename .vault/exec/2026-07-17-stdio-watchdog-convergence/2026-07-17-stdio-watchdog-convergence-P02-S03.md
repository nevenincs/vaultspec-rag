---
tags:
  - '#exec'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:69931142b4a8128f0e95ef7776dfd5fb7bfccf9ea9a79c5e7cbc215916eef110'
step_id: 'S03'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-plan]]"
---

# Add unit coverage for the resolver and the layered arming composition

## Scope

- `src/vaultspec_rag/tests/test_stdio_lifetime.py`

## Description

- Unit tests: pipe-creator resolves the spawning process from a real
  piped child; console stdin fails open; a resolved client suppresses
  the chain; explicit+client deduplicate; an unopenable client falls
  back to the chain; chain targets are prunable; `open_watched` refuses
  impossible PIDs.

## Outcome

27 unit tests pass.

## Notes

None.
