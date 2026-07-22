---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P01.S01 singleton test isolation`

## Scope

Independent safety and intent review of the final `W01.P01.S01` fixture patch against the
accepted isolation decision and managed-singleton rule.

## Findings

No critical, high, medium, or low findings were identified. Both paths are created beneath
one session root and overwrite ambient values unconditionally. Both configuration caches
reset on every boundary, ambient values return only at session teardown, and function
fixture ordering preserves narrower isolated overrides.

The canonical mapping is immutable, closing the only review recommendation: a fixture
consumer cannot alter the values used by later autouse rearming. Focused real discovery,
heartbeat, identity, and lock coverage completed 24 tests without touching operator-global
paths.

### isolated-binary-source | medium | Session isolation hid the verified Qdrant install

A later live-fixture run found that overriding the status directory before nested service
setup also redirected managed-binary resolution to the empty session tree. The nested
fixture could no longer obtain a verified source to mirror and stopped before exercising
its job assertions. The corrected session fixture resolves the provisioned binary and
manifest while the ambient configuration is still active, then copies them into the
pytest-owned session status tree after isolation. Nested fixtures read only that isolated
copy, while the production supervisor still re-hashes it against the pinned manifest.

The first correction placed copying before the restoration `try/finally`; independent
review classified that entry-failure restoration gap as Medium. The final revision moves
both environment mutation and copying inside the protected block. Re-review found no
remaining findings. The safe mirror test, Ruff, formatting, ty, BasedPyright, and diff
checks passed, and host files and service identity remained unchanged.

Status: **PASS** after follow-up. There are no unresolved findings at any severity.

## Recommendations

Proceed to the separate production containment-guard Step; do not claim same-test mutation
immunity from fixture boundaries alone.
