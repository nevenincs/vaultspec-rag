---
tags:
  - '#research'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:fae03b3611aa6fd232eb8efd3141cb90938a0e08610bae4349dae640428799c2'
related:
  - "[[2026-06-18-watcher-targeted-reindex-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-28-pressure-management-adr]]"
  - "[[2026-07-28-convergence-cost-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
---

# `adaptive-watcher-control` research: `adaptive automatic convergence`

Automatic convergence already preserves exact live-process scope, durable retry intent,
quiet-tree flushing, and canonical job ownership, but fixed timing cannot distinguish a
small burst from sustained churn or service pressure. The evidence favors a durable
per-root/source controller plus a service-owned fair admission arbiter; the ADR must settle
the state model, persistence envelope, policy bounds, fairness and freshness guarantees,
and canonical telemetry contract.

## Findings

### Fixed timing is the only admission policy

`WatcherConfiguration` exposes debounce and cooldown, while each convergence slot holds
volatile paths, last-success time, and replacement backoff. Admission uses the maximum of
the fixed cooldown and replacement deadline without reading workload or pressure evidence
(`src/vaultspec_rag/watcher_runtime.py:120`, `src/vaultspec_rag/watcher_runtime.py:133`,
`src/vaultspec_rag/watcher_intake.py:447`). The one-second `awatch` idle yield is the
accepted quiet-tree liveness mechanism and must be generalized into deadline-driven wakeups,
not removed (`src/vaultspec_rag/watcher_intake.py:67`,
`src/vaultspec_rag/watcher_intake.py:307`).

### Exact scope is durable only as intent

Live slots retain held, pending, and per-attempt path sets across edits and running attempts
(`src/vaultspec_rag/watcher_runtime.py:144`). The versioned retry ledger persists generation,
circuit, retry, and attempt identity but not paths or first/last observation timestamps
(`src/vaultspec_rag/watcher_retry.py:98`). Restart with pending intent therefore fails closed
as `full_reindex_required` when exact scope was lost (`src/vaultspec_rag/watcher_retry.py:241`).
Deletes already use durable prior ownership before entering the appropriate source slot, and
rename is represented as delete plus add (`src/vaultspec_rag/watcher_intake.py:95`,
`src/vaultspec_rag/watcher_intake.py:117`). A bounded, versioned relative-path set can close
the restart gap without weakening typed refusal for corrupt, foreign, oversized, or unknown
scope.

### Canonical service measurements already exist

The controller can consume index limiter occupancy and waiters
(`src/vaultspec_rag/concurrency.py:94`), stable machine-pressure tiers and reasons
(`src/vaultspec_rag/pressure.py:86`), GPU evidence
(`src/vaultspec_rag/_job_evidence.py:114`), job degradation and progress
(`src/vaultspec_rag/server/_routes_jobs.py:430`), bounded search activity and latency
(`src/vaultspec_rag/server/_search_activity.py:86`), and storage survey evidence
(`src/vaultspec_rag/server/_routes_storage.py:285`). Watcher status currently exposes only
configuration and watched roots (`src/vaultspec_rag/server/_routes_registry.py:58`,
`src/vaultspec_rag/api.py:1130`), so controller facts need one service-domain snapshot
projected through every adapter.

### Existing execution ownership should remain unchanged

Sources reconcile in fixed vault, code, document order inside each root, while roots have
independent watcher tasks (`src/vaultspec_rag/watcher_intake.py:156`). This does not prove
cross-root/source fairness. `JobManager` already owns execution and deduplication, so moving
watcher policy into it would mix generic job lifecycle with filesystem convergence. Extending
only the current slot is a smaller change but leaves persistence, fairness, telemetry, and
policy distributed. A pure per-root/source controller with a service-owned automatic-lane
arbiter separates collection/admission from execution and avoids a new global execution
lock.

### The ADR must make bounds and recovery explicit

The present independent nonnegative debounce/cooldown overrides
(`src/vaultspec_rag/config/_settings.py:392`, `src/vaultspec_rag/config/_schema.py:344`)
cannot express maximum freshness, fairness, measurement staleness, hysteresis, recovery
jitter, or scope-size limits. The ADR must name states and stable reason codes, atomic
path/state transitions, exact recovery fencing, adaptive formulas, missing-measurement
semantics, hard freshness and fairness bounds, event/deadline wakeups, the terminal rebuild
lifecycle, and deterministic virtual-clock/model-test seams. Production trace material was
limited to issue #470's reported 78-second median run and 30-second cooldown; no raw trace
artifact was available for replay.

## Sources

- `src/vaultspec_rag/watcher_runtime.py:120`
- `src/vaultspec_rag/watcher_runtime.py:133`
- `src/vaultspec_rag/watcher_runtime.py:144`
- `src/vaultspec_rag/watcher_intake.py:67`
- `src/vaultspec_rag/watcher_intake.py:95`
- `src/vaultspec_rag/watcher_intake.py:117`
- `src/vaultspec_rag/watcher_intake.py:156`
- `src/vaultspec_rag/watcher_intake.py:307`
- `src/vaultspec_rag/watcher_intake.py:447`
- `src/vaultspec_rag/watcher_retry.py:98`
- `src/vaultspec_rag/watcher_retry.py:241`
- `src/vaultspec_rag/concurrency.py:94`
- `src/vaultspec_rag/pressure.py:86`
- `src/vaultspec_rag/_job_evidence.py:114`
- `src/vaultspec_rag/server/_routes_jobs.py:430`
- `src/vaultspec_rag/server/_search_activity.py:86`
- `src/vaultspec_rag/server/_routes_storage.py:285`
- `src/vaultspec_rag/server/_routes_registry.py:58`
- `src/vaultspec_rag/api.py:1130`
- `src/vaultspec_rag/config/_settings.py:392`
- `src/vaultspec_rag/config/_schema.py:344`
- https://github.com/nevenincs/vaultspec-rag/issues/470
