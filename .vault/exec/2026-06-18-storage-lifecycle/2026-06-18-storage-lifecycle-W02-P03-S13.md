---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S13'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a gated GET storage route, bounded and filterable, and register it in the route table

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

Shared supersession record for the storage-lifecycle steps that described the
service-owned destructive HTTP control plane. The feature shipped through pull request 196
with a different, deliberately chosen architecture: the destructive operations - delete,
prune, and migrate - run as CLI verbs that open their own client directly to the managed
loopback Qdrant server and call the service-domain storage functions in-process, rather
than as gated HTTP routes on the daemon with CLI-to-service HTTP adapters. The user
directed this reconciliation to the shipped design and explicitly not to build the
destructive HTTP control plane. The only service-owned surface the ADR sanctions and that
this reconciliation built is the read-only survey route, tool, and service-first CLI path.

This record resolves the following steps as superseded by that decision, with the rationale
captured here so each tick is honest rather than silent: the gated GET storage route (S13);
the CLI-to-service survey HTTP adapter (S16); the single-root in-process local-mode survey
path (S17), since storage operations require server mode and a local store has a single
namespace and nothing to reconcile; the POST delete route (S22) and its CLI-to-service
delete HTTP adapter (S24); the POST prune route (S28) and its prune HTTP adapter (S30); the
GPU-consumer reuse in migrate (S40), which is not applicable because migrate is copy-only
and re-embeds nothing, so no forward pass and no GPU lock are involved; and the POST migrate
route (S41) with its migrate HTTP adapter (S43).

## Outcome

The superseded steps are closed against the recorded rationale, not built. The destructive
verbs are delivered CLI-direct (survey, delete, prune, migrate all function under the
`server storage` group), the read-only survey is the single service surface, and the
local-mode survey and the destructive HTTP routes and adapters the original plan named are
formally retired. The plan's reconciliation note carries the same divergence summary in the
plan body.

## Notes

This is a reconciliation closure, not new implementation, for the superseded steps S13, S16,
S17, S22, S24, S28, S30, S40, S41, and S43. The read-only survey surface those steps' phases
also touched was genuinely built and is recorded in its own step records. S40's
inapplicability is structural: a backend migrate copies vectors and payloads as-is and never
re-embeds, so there is no GPU consumer to reuse and no GPU lock scope to respect.
