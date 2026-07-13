---
tags:
  - '#research'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - '[[2026-06-18-storage-lifecycle-adr]]'
  - '[[2026-06-27-rag-broker-affordances-adr]]'
---

# `control-plane-affordances` research: `root-scoped survey lookup and stop --json parity`

The vaultspec-dashboard team reported two control-plane gaps. First, no service
surface answers "what is the collection prefix / which collections belong to
root X", so their embedding-scroll path recomputes rag's internal blake2b
prefix by hand (their RCR-003 sanctioned exception). Second, `server stop`
rejects `--json`, breaking envelope parity with `server start --json` and
`server status --json` for a supervising broker. This research grounds both
gaps in the governing decisions and the shipped code to scope a decision.

## Findings

### F1 - The prefix contract is private and the dashboard duplicates it

`root_collection_prefix()` in `src/vaultspec_rag/store.py` derives the
per-root namespace as `r{blake2b(digest_size=6, normcase(resolved(root)))}_`.
It is an internal function with no public surface; the dashboard reimplements
the same hash, which breaks silently if the derivation ever changes. Exposing
the mapping through a service surface is what lets them delete the exception.

### F2 - The survey already carries the data but cannot answer a root-scoped question

`GET /storage/survey` (`src/vaultspec_rag/server/_routes.py`,
`_gather_storage_survey`) returns per-namespace `prefix`, `root`, `status`,
`collections`, `points`, and `footprint_bytes`. However the route accepts only
`status` and `limit` (`_STORAGE_SURVEY_PARAMS` in
`src/vaultspec_rag/serviceclient/_transport.py`), so a caller wanting one
root's namespace must page the whole survey and match client-side - and gets
no answer at all for a root not yet in the manifest.

### F3 - The storage-lifecycle ADR already sanctioned a root filter that never shipped

The `2026-06-18-storage-lifecycle-adr` (D3/D8) specified the survey as
"bounded, filterable (`--orphaned`, `--unknown`, `--root`, `--since`)". Only
the status filters shipped; the CLI `server storage survey` exposes
`--orphaned`/`--unknown` applied client-side, and the MCP `survey_storage`
client (`src/vaultspec_rag/mcp/_admin_client.py`) passes `status`/`limit`
only. A `?root=` filter is therefore completing an accepted decision, not a
new architectural direction.

### F4 - A pure filter is not enough; the lookup must compute the prefix for the queried root

Filtering namespaces by root only answers for already-indexed roots present in
the manifest. The dashboard's need is the derivation itself: given a root,
which collections would/do belong to it. The route should resolve
`root_collection_prefix(root)` server-side and return it (e.g. a top-level
`queried_root: {root, prefix}` object) alongside the (possibly empty) matching
namespaces, so an unindexed root still yields the authoritative prefix and the
dashboard never recomputes the hash.

### F5 - Surface ownership: the survey route, not status or health

`service-domain-owns-operability` requires one service-domain behavior adapted
by CLI and MCP. `/health` is identity/liveness (pid, token) and deliberately
light; `server status` is per-config lifecycle state, while the dashboard may
ask about arbitrary roots. The survey is already the one read-only storage
surface shared by route, CLI, and MCP, and already classifies through the
persisted prefix-to-root manifest. Extending it keeps a single classification
authority; adding a parallel lookup to status or health would fork it.

### F6 - `server stop --json` was already named as the follow-on pathway

The `2026-06-27-rag-broker-affordances-adr` shipped `server start --json`
(status `already_running`/`started`, one envelope per exit path) and
explicitly listed "a `server stop --json` sibling" under pathways opened. Its
codification candidate - broker-facing lifecycle verbs emit exactly one
structured envelope on every exit path and treat already-satisfied as success
\- is the contract stop must satisfy.

### F7 - Stop has six exit paths, one of which is a masked failure

`service_stop` in `src/vaultspec_rag/cli/_service_lifecycle.py` exits through:
stopped (default path), stopped-via-`--port`, reclaimed machine singleton,
not-running (idempotent success), stale-discovery cleaned (pid confirmed
dead), and stop-skipped (identity unconfirmed on a live pid, service left
running - both the default and `--port` variants). All six currently exit 0.
Under the broker contract, skip-with-service-still-running is a failure the
broker must see (`ok:false`, non-zero exit); not-running is `already_stopped`
success. The start implementation provides the envelope machinery to mirror:
`_emit_json`, `_start_success`, `_fail_start` with a `service.stop` command
tag.

### F8 - Existing envelope idiom to match

Start's JSON contract: success `{ok: true, command: "service.start", data: {status, ...}}`; failure `{ok: false, command, error, message, data}`,
suppressing all human/console output in `--json` mode (one clean envelope on
stdout). Survey JSON already exists on the CLI via `--json`
(`_emit_survey_json`). The stop and root-lookup additions inherit these idioms
rather than inventing new shapes.

### F9 - Test surfaces

Integration coverage lives in
`src/vaultspec_rag/tests/integration/test_storage_survey_service.py` (route
envelope, bogus status, limit) and the lifecycle tests around start
`--json`. New coverage: `?root=` returns the computed prefix for both an
indexed and an unindexed root; CLI `--root` and MCP arg pass-through; stop
`--json` envelope per exit path (at minimum stopped, not-running, and the
skip failure), asserting exit codes.

## Sources

- `src/vaultspec_rag/store.py` - `root_collection_prefix()` derivation
- `src/vaultspec_rag/server/_routes.py` - `/storage/survey` route and gatherer
- `src/vaultspec_rag/serviceclient/_transport.py` - `_STORAGE_SURVEY_PARAMS`
- `src/vaultspec_rag/cli/_service_storage.py` - `server storage survey` CLI
- `src/vaultspec_rag/mcp/_admin_client.py` - `survey_storage` MCP client
- `src/vaultspec_rag/cli/_service_lifecycle.py` - `service_stop`, start envelope helpers
- ADR `2026-06-18-storage-lifecycle-adr` (D2, D3, D8)
- ADR `2026-06-27-rag-broker-affordances-adr` (pathways opened, codification candidate)
- vaultspec-dashboard team feedback (2026-07-13, RCR-003 sanctioned exception)
