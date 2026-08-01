---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:e86231427428c2ef47d6e70220674b220fab2b88e32be89a0ee30bc39af9eb2c'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P03.S06 heartbeat snapshots`

## Scope

Architecture and race review of canonical daemon snapshots, independent view repair, and
the heartbeat quiescence boundary against ADR decision D2.

## Findings

No critical, high, medium, or low findings remain. The new snapshot builder reads no prior
discovery document. It requires the daemon's live service port and identity token, fixes PID
authority to the current process, retains one start timestamp, validates the lifecycle phase,
and adds only daemon-observed Qdrant identity.

Status replacement uses the existing bounded cross-process write lock, overwrites malformed
or missing content with a complete snapshot, flushes and fsyncs before unique atomic
replacement, and remains protected by pytest singleton containment. Machine publication
uses the retained owner lease from S04. Each view has a separate guarded attempt, so an
operator-view failure cannot suppress pointer repair and a pointer failure cannot erase a
successful operator snapshot.

The publisher holds one reentrant lifecycle guard across snapshot construction and both
writes. Quiescence acquires that same guard before marking publication stopped: an already
running worker completes first, while a worker arriving later observes the stop flag and
performs no filesystem effect. Cleanup also marks stopping under the guard and deletes the
pointer only through the retained lease.

Status: **PASS**. S06 defines the convergent mechanism; S07 must replace the existing
read-before-merge heartbeat and unauthenticated shutdown paths completely.

## Recommendations

Pass one publisher from lock acquisition through phase stamps, the heartbeat loop, shutdown
cleanup, and final lease release. Do not retain the old PID-derived pointer writer.
