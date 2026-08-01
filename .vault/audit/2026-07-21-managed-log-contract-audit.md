---
tags:
  - '#audit'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:c0c848f8036ac6b732ec7fe84a10ab133310a81a75b952f534e65871f3aca819'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - "[[2026-07-21-managed-log-contract-research]]"
---

# `managed-log-contract` audit: `managed logging implementation safety and intent review`

## Scope

Audited the complete managed-log implementation against the accepted ADR, research,
reference, implementation plan, repository rules, and HIGH reviewer safety criteria. The
review covered generic retention configuration, both rotating writers, source-aware bounded
reading, filter and grouping semantics, authenticated HTTP, transport, live and offline CLI
behavior, MCP scope, real-behavior tests, and operator documentation.

Status: **PASS**. The initial review found one High drain-lifecycle race and one Medium cleanup
weakness. Both were revised, retested, and independently re-reviewed. No Critical or High
finding remains open.

## Findings

### drain-writer-exclusivity | high | Resolved timed-out drain ownership race

The initial implementation cleared `_drain_thread` after a bounded join even if the thread
remained alive, permitting restart to create a second unsynchronized rotating sink. The
revision makes `_join_output_drain` retain a live reference, makes `stop` preserve that guard,
and makes both `restart` and `spawn` refuse replacement until the original drain exits. A real
parent-and-grandchild inherited-pipe test holds EOF beyond the join timeout, proves restart is
refused without replacing the process or writer, releases the pipe, and proves a later spawn
succeeds. Focused re-review closed the finding.

### sink-failure-cleanup | medium | Resolved cleanup escape from pipe draining

The original persistence-disable path could allow a secondary close error to escape and end
the drain. The revision detaches the failed sink before best-effort cleanup and suppresses
`OSError` and `ValueError` during both failure and final cleanup. Child output therefore keeps
flowing into the recent-output ring even when persistent logging fails. Focused re-review
closed the finding.

### bounded-retention | low | Both managed writers enforce one independent finite policy

The service handler and Qdrant raw sink consume the same positive byte threshold and
non-negative backup count. Qdrant rollover closes before shifting, securely reopens, prunes
stale numeric generations, supports zero-backup truncate mode, handles pre-existing oversized
files, and preserves recent diagnostics when persistence fails. Real service and Qdrant tests
exercise these paths.

### bounded-reader | low | Sparse and block-boundary retrieval preserves source truth

`read_managed_logs` discovers numeric generations without assuming contiguity, reverse-reads
only enough bytes to satisfy each source budget, preserves within-source order, retains empty
groups, and tolerates read and rollover races. Multibyte records crossing the reverse-read
block are covered with and without a final newline.

### operator-contract | low | Live and offline adapters share one grouped shape

Authenticated HTTP and offline CLI use the same reader and shaping helpers. Filtered requests
search at most 5,000 records per source before applying the requested per-source tail. `all`
keeps service and Qdrant separate, invalid sources are structured errors, and transport errors
are not rendered as successful empty results.

### clean-break-and-scope | low | Obsolete paths are removed without expanding MCP

Production contains no legacy retention properties, old environment variables,
`read_service_log`, service-only payload identity, activity parser, or `--raw` compatibility
path. Managed logs remain absent from the public MCP surface.

### test-and-documentation-integrity | low | Verification uses production behavior and accurate operator text

Added tests use real files, subprocess pipes, ASGI routes, a live Uvicorn socket, and isolated
service processes without new fakes, mocks, stubs, patches, monkeypatches, skips, or xfails.
Operator references accurately describe generic retention, the approximate 120 MiB aggregate
default, source selection, grouped JSON, bounded filtering, and post-crash local reads.

## Recommendations

- Keep the inherited-pipe regression and strict static gates in the managed-log verification
  set so future supervisor changes cannot weaken the one-writer invariant.
- Track the unrelated 40 ms admin authentication deadline timing failure separately; it is not
  caused by this feature and does not invalidate the managed-log test matrix.
