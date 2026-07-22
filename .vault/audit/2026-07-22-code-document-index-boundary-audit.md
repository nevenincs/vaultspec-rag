---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` audit: `Final implementation review`

## Scope

Reviewed committed `HEAD` at `d124d286` against the accepted research, ADR, and
implementation plan. The review covered path-neutral admission in
`_content_policy.py` and `_resolved_policy.py`; fail-closed policy resolution at
mutation entry points; code/document model, collection, metadata, clean, search,
and lock isolation; generation and route-migration replay in `_run_ledger.py`,
`_run_checkpoint.py`, `_document_checkpoint.py`, and `_route_migration.py`;
watcher recovery; bounded streaming and GPU-lock placement; canonical source-type
handling across the Python API, CLI, HTTP, MCP, and service transport; and the
integrity of the feature's tests.

The committed tree contains no client-specific identifier or built-in directory
classification. The conventional profile is a path-agnostic source-extension set,
while parser-only formats require caller-authored routing. Focused source-type,
policy, migration, and watcher verification completed with 27 passing tests and
one intentionally deselected model-backed test. A direct real-store replay and a
direct Python API call were also used to validate the findings below.

## Findings

### migration-replay-evidence | high | Pending cleanup can delete the last good origin after the destination has been replaced

`reconcile_origin_after_destination` correctly requires a complete destination
file before it writes a pending journal row, but `resume_pending_migrations` later
trusts that historical row unconditionally. It does not verify that the named
destination generation is still published, that its retained destination point
identifiers remain present, or that a later clean generation has not replaced the
destination collection. A crash after `RouteMigrationJournal.begin`, followed by
an interrupted clean rebuild of the destination, therefore leaves a pending row
whose replay deletes the origin even though the destination is empty. A direct
real-store reproduction created both owners, journaled destination confirmation,
dropped and recreated the destination collection, then replayed the journal;
replay reported one completed migration and left both collections with zero
points. This violates destination-first durability and can cause data loss after a
two-failure sequence.

### watcher-prior-ownership | medium | A newer incomplete clean generation can hide the stored owner of a deleted path

`prior_stored_owners` asks `RunLedger.latest_generation` for one generation per
kind and checks only that generation's file states. `latest_generation` orders all
terminal and non-terminal generations by update time without requiring successful
publication. Non-clean generations carry a prior published manifest, but clean
generations intentionally do not. If a clean generation starts or fails before it
replaces the stored collection, it becomes the latest generation while omitting
the still-stored paths from the prior published generation. A subsequent delete
event can therefore miss the actual prior owner; when current routing names the
other kind, the watcher schedules only that kind and leaves the old point stale.
The current watcher test covers one generation but not a published owner obscured
by a newer incomplete clean generation.

### python-clean-source-validation | medium | The Python clean facade silently accepts unknown source types

The public `clean` facade uses membership checks on its `clean_type` string rather
than the closed `parse_source_type` authority. At runtime an unsupported value
closes the project registry slot, mutates no collection, and returns an empty
success list instead of a structured unknown-source error. A direct call with an
unsupported value returned `[]`. CLI, HTTP, MCP, and service transport reject or
normalize source types explicitly, so this remaining Python API path violates the
same exhaustive public contract and can make automation report a cleanup that did
not occur.

## Recommendations

Treat the findings as release-blocking until the destination-first invariant is
restored and the public contract is exhaustive.

For migration replay, persist enough destination evidence to revalidate the exact
published generation and retained point set before every origin deletion. Invalidate
or supersede pending rows when a destination collection is dropped, and retain the
origin whenever current destination evidence is absent. Add a real-store regression
covering confirmation, crash, destination clean/drop, interrupted replacement, and
replay.

For watcher recovery, resolve prior ownership from the newest successfully
published generation that still certifies the path, with explicit handling for an
in-progress destructive generation. Add a watcher regression where a published
owner is followed by an incomplete clean generation before a delete event.

For the Python facade, parse `clean_type` through the closed source-type authority
before closing registry state or opening storage, map the combined selection
explicitly, and add direct in-process tests for canonical values, permitted
compatibility aliases if intended, and structured rejection of unknown values.
