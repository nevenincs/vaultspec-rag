---
tags:
  - '#adr'
  - '#qdrant-long-paths'
date: '2026-07-14'
modified: '2026-07-27'
related:
  - "[[2026-07-13-control-plane-affordances-audit]]"
  - "[[2026-07-13-storage-autoprune-safety-research]]"
  - '[[2026-07-27-qdrant-long-paths-grounding-research]]'
---
# `qdrant-long-paths` adr: `verbatim storage paths make Windows path length a non-issue` | (**status:** `accepted`)

## Problem Statement

Qdrant 1.18.2's gridstore fails every collection create on Windows once the
storage directory exceeds ~105 characters ("The system cannot find the path
specified. (os error 3)"): the internal
`collections/<name>/segments/<uuid>/...` layout crosses the classic 260-char
MAX_PATH, and the `LongPathsEnabled` registry setting does not help. The
grounding lives in the control-plane-affordances audit
(daemon-reindex-root-cause and qdrant-pin-followup findings): 1.18.2 is the
latest upstream release, so no pin bump exists, and the current mitigation is
only a supervisor warning above 90 characters. The operator directed a local
hardening instead of an upstream issue.

## Considerations

Evidence gap: the retained ADR body has no separately labelled Considerations section.

## Considered options

- **O1 - extended-length (verbatim) paths (chosen).** Pass
  `\\?\`-prefixed absolute paths as the qdrant child's storage and snapshots
  env config. Empirically verified 2026-07-14 against the pinned binary and
  the production collection schema: plain paths fail at 140 and 200
  characters; verbatim paths succeed at 145 and 205. Zero new machinery.
- **O2 - NTFS junction alias.** Create a short junction pointing at the
  configured dir and hand qdrant the alias. Works but adds filesystem state
  to create, verify, and clean up, plus failure modes of its own. Not needed
  given O1's result.
- **O3 - refuse long paths at spawn.** Legible but does not let the operator
  keep their configured location; strictly worse than O1.
- **O4 - auto-relocate to a short directory.** Rejected: silently splitting
  the store from the configured path makes data appear lost when config and
  reality diverge.

## Constraints

Evidence gap: the retained ADR body has no separately labelled Constraints section.

## Implementation

The supervisor's child-env builder converts the storage and snapshots paths
to Windows extended-length form: absolute-resolve, then prefix `\\?\`
(drive paths) or `\\?\UNC\` (UNC paths); non-Windows platforms and
already-prefixed paths pass through unchanged. Applied unconditionally on
Windows so the translation is exercised by every run rather than sleeping
behind a threshold. The spawn-time >90-character warning is removed - the
condition is no longer a failure mode. All Python-side bookkeeping
(footprints, archives, sweeps) keeps using the plain configured paths; only
the child's env changes. The integration test harness returns to plain
pytest tmp paths for isolated qdrant storage, which regression-exercises
long paths on every integration run, and a dedicated regression test spawns
a supervisor with a >140-character storage dir and creates a real
collection.

## Rationale

Evidence gap: the retained ADR body has no separately labelled Rationale section.

## Consequences

Windows path length stops being an operational constraint for the store
location; the test-harness short-path workaround and its stale-dir sweep are
deleted rather than maintained. Risk accepted: verbatim paths disable Win32
path normalization, so the helper must always feed it resolved absolute
paths - the helper owns that, with unit coverage for drive, UNC, idempotent,
and non-Windows cases.
