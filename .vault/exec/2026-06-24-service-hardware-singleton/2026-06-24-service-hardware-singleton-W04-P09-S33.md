---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S33'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# After a successful orphan reap, poll for port/storage-handle release before spawning so the fresh child cannot lose a reap-to-spawn bind race (review LOW-1)

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- After a successful orphan reap, poll for port/storage-handle release before
  spawning so the fresh child cannot lose a reap-to-spawn bind race.
- Add `_port_is_listening`, a loopback TCP connect probe, and
  `_wait_for_port_release`, which polls until the port stops listening, settles
  briefly so the storage-lock handle is released too, and reports success.
- Call the port-release wait between the reap and the spawn fall-through, failing
  with a named, actionable cause when the port does not free in time rather than
  spawning a doomed child.
- Extract the whole reap-then-spawn block into `_reap_orphan_before_spawn` to
  keep the supervised-start function within the cognitive-complexity gate.
- Add tests for the listening/free probe, the held-port timeout, the free-port
  fast return, and a release-mid-wait case, all against real loopback sockets.

## Outcome

The reap-to-spawn handoff is now deterministic: the supervisor waits for the
reaped child's listening socket to be released before spawning, so the fresh
child no longer loses a bind race against the prior child's lingering socket or
storage handle. A port that does not free in time yields a named failure instead
of a doomed spawn. The supervised-start function stays under the complexity gate
after the extraction.

## Notes

The held-port test uses a real accepting HTTP server (not a bare `listen()`
backlog) so the probe observes a genuinely listening port throughout, matching
the orphan-holder reality.
