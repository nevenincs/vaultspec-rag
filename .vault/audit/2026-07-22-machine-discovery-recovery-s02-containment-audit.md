---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P01.S02 containment guard`

## Scope

Independent safety and intent review of the exact `W01.P01.S02` production diff against
the accepted owner-authenticated discovery decision and the managed-singleton isolation
rule. The review covered the pytest containment authority, every changed singleton
write, lock, spawn, signal, and deletion boundary, fail-before-effect ordering,
production inertness, import topology, exception propagation, Windows and POSIX process
paths, and shared-worktree scope.

## Findings

No critical, high, medium, or low findings were identified.

The process-local registered root remains the authority after activation; mutable
environment variables serve only as child-process transport and cannot re-anchor that
root. The aggregate guard validates both configured singleton anchors and each explicit
effect target before directory creation, file open or unlink, OS-lock acquisition or
probe, process spawn, or signal. The machine-pointer cleanup path performs its guard
immediately before unlink, so best-effort cleanup cannot swallow a containment failure.

The guarded boundaries cover status-directory creation and write locking, machine lock
acquire, release, and live-holder probing, machine-pointer publication and deletion,
managed Qdrant identity publication and orphan reaping, supervised Qdrant spawn and
stop, service log-directory creation, service spawn, and service termination. Lower-level
platform branches remain reachable only after their shared guard, preserving equivalent
fail-closed behavior for Windows and POSIX.

Ordinary production calls return from the guard before importing or resolving
configuration. Guard imports remain local and leaf-directed, so the change introduces no
import cycle or widened import-time side effect. `ManagedSingletonIsolationError` is not
captured by the existing best-effort `OSError` handlers, and the pointer-delete guard is
outside its unlink suppression, so violations remain visible and fail closed.

Status: **PASS**. There are no unresolved findings at any severity.

## Recommendations

Proceed to `W01.P01.S03` real-behavior adversarial coverage. Keep the containment helper
at the first effect boundary when later owner-only publication primitives replace the
current pointer writers, and do not weaken process-local root pinning into mutable
environment authority.
