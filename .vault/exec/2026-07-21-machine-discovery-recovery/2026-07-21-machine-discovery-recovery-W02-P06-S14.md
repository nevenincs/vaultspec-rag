---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:31969a9afce83caf43e9e22580beba2bd10922aeb4c3e444812b3a6e0a257b89'
step_id: 'S14'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Adapt server status rendering and exit semantics to ready, degraded, and absent discovery verdicts

## Scope

- `src/vaultspec_rag/cli/_status_render.py`

## Description

- Probe the live signals for an address the machine resolution produced, so a typed
  resolution can be composed into a canonical verdict.
- Consult the machine singleton before declaring a service stopped when this status
  directory holds no record of its own.
- Render a discovery-derived verdict in summary, verbose, and JSON form, carrying the
  resolution evidence into each.

## Outcome

A live singleton holder is no longer rendered as an absent service. An operator whose
status directory differs from the daemon's now sees either the running service or a named
degraded condition, with the holder and pointer evidence behind it.

## Notes

The change is confined to the branch where this status directory holds no record. Where a
record exists, the established four-signal derivation still owns the verdict: it carries
richer liveness evidence than the pointer alone, and rewriting it would have changed
behaviour well beyond the discovery contract this step is responsible for.

The exit-code contract is unchanged. A degraded verdict reports the existing fault code,
so no supervising broker has to learn a new one.
