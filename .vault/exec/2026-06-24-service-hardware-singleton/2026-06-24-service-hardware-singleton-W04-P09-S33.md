---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S33'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-hardware-singleton with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S33 and 2026-06-24-service-hardware-singleton-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The After a successful orphan reap, poll for port/storage-handle release before spawning so the fresh child cannot lose a reap-to-spawn bind race (review LOW-1) and ## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
