---
tags:
  - '#audit'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-qdrant-store-resilience-adr]]"
---

# `qdrant-store-resilience` audit: `Code review of the corrupt-collection recovery`

## Scope

Independent code review of the detect-quarantine-retry recovery (commit
`466cdfb`) against the ADR's QR1-QR5: the supervised retry loop and helpers in
`_supervise.py`, the `server qdrant quarantine` verb in `_service_qdrant.py`, and
the tests. Focus on retry termination, the abstain-when-uncertain contract, the
quarantine move's reversibility, parser robustness, CLI gating, and test quality.
All findings were actioned in the follow-up commit `cd2bb2a`.

## Findings

- **HIGH - slow load misdiagnosed as corrupt (QR4 violation).** `start()` treated
  any `wait_ready()` failure as a corrupt collection without checking whether the
  child had actually died. A readiness timeout on a healthy-but-slow store (the
  supervisor's own docstring cites ~131s stores) left the child alive; the loop
  stopped it and quarantined a healthy collection - strictly worse than the
  timeout it replaced. **Resolved:** `start()` captures `is_alive()` before
  `stop()` and only attempts detection-and-quarantine when the child has died; a
  live-child timeout raises without touching the store. Regression test:
  `test_readiness_timeout_with_a_live_child_quarantines_nothing`.

- **MEDIUM - whole-buffer co-occurrence.** Detection checked the failure marker
  and the collection name independently across the whole 50-line buffer, and the
  marker set included non-failure-specific words (`segment`, `wal`, `snapshot`,
  `recover`) common in healthy logging. A global fault naming no collection plus
  an incidentally-logged healthy collection could mis-finger it. **Resolved:**
  detection now requires the name and a marker on the *same line*, and the
  markers are narrowed to `panic`/`corrupt`/`failed to load`/`cannot load`/
  `unable to load`/`could not load`/`error loading`.

- **MEDIUM - tail captured before the drain join.** The panic tail was read
  before `stop()` joined the output-drain thread, so a just-died child's final
  flushed line could be missed, spuriously abstaining (and a test-flake source).
  **Resolved:** the tail is captured after `stop()`.

- **MEDIUM - uncaught OSError on the quarantine move.** `_quarantine_collection`'s
  `rename` could raise (e.g. files held by a live server on Windows), surfacing
  as an unhandled traceback on both the auto path and the CLI verb. **Resolved:**
  both call sites catch `OSError`; the auto path raises an actionable
  `RuntimeError`, the verb emits the standard error envelope and hints to stop the
  server first.

- **LOW - test/verb polish.** Added `start()`-level coverage for the abstain path
  (dead child naming no on-disk collection) and the live-child timeout; unified
  the listing verb's JSON `verb` string with its sibling.

- **INFO - sound aspects (confirmed).** The retry is genuinely bounded
  (`quarantined < _MAX_QUARANTINES_PER_START` forces a loud raise); quarantine is
  move-not-delete to a same-filesystem timestamped dir (reversible, forensics-
  preserving); longest-name-first resolves substring collisions; and the
  quarantine dir is a true sibling of `collections/` (not under it), correctly
  resolving the ADR's literally-written `collections/.quarantine/`.

## Recommendations

All blocking and medium findings are resolved in `cd2bb2a`; the feature is sound
for merge. No durable cross-feature rule emerged - the recovery behavior is
feature-local, so no codification (an empty codification is the expected outcome
for this ADR). Future hardening, if the failure recurs in the field: persist a
per-collection quarantine count so a collection that re-corrupts immediately
after re-index is not endlessly re-quarantined, and add an operator command to
clean or restore the `quarantine/` directory.
