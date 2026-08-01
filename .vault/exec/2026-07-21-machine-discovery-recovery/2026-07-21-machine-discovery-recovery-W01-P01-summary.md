---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8e156546f0d0af274a798593a78a97c34746d4f31ce8a059612e9f29c03760d2'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` `W01.P01` summary

The phase makes pytest ownership structural at setup and enforceable at every production
machine-singleton effect, then proves the boundary with hostile ambient and same-test
configuration against real files, locks, exec children, and processes.

- Modified: `conftest.py`
- Modified: `src/vaultspec_rag/tests/conftest.py`
- Modified: `src/vaultspec_rag/_test_isolation.py`
- Modified: `src/vaultspec_rag/_machine_lock.py`
- Modified: `src/vaultspec_rag/serviceclient/_discovery.py`
- Modified: `src/vaultspec_rag/qdrant_runtime/_resolve.py`
- Modified: `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- Modified: `src/vaultspec_rag/cli/_process.py`
- Modified: `src/vaultspec_rag/server/_lifecycle.py`
- Created: `src/vaultspec_rag/tests/test_managed_singleton_isolation.py`
- Created: three Step Records, three focused audits, and this phase summary
- Updated: the machine-discovery plan and feature index

## Description

S01 forces status and Qdrant storage beneath one immutable session-owned root, resets both
configuration caches at test boundaries, and preserves verified access to the provisioned
Qdrant binary through an isolated mirror. S02 adds a process-pinned aggregate containment
guard before status, lock, pointer, identity, logging, spawn, stop, and reap effects while
remaining inert outside pytest. S03 proves that hostile inherited paths, mutable guard
transport, either independently escaped configured anchor, and explicit production process
control all fail before mutation or signalling.

Final verification passed seven focused adversarial tests, the prior 59-test singleton and
lifecycle suite, six post-collision lock/pointer tests, Ruff format and lint, BasedPyright
with zero diagnostics, plan validation, and the vault structural checks. Both formal audits
finish with no unresolved finding at any severity. No operator daemon, operator singleton
path, or unrelated shared-worktree change was mutated.
