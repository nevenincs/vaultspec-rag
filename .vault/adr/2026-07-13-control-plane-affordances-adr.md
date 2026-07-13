---
tags:
  - '#adr'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - "[[2026-07-13-control-plane-affordances-research]]"
  - "[[2026-06-18-storage-lifecycle-adr]]"
  - "[[2026-06-27-rag-broker-affordances-adr]]"
---

# `control-plane-affordances` adr: `root-scoped survey lookup and stop --json parity` | (**status:** `accepted`)

## Problem Statement

The vaultspec-dashboard team, a consuming broker of this service, reported two
control-plane gaps. First, no service surface answers "what is the collection
prefix, and which collections belong to root X" - so their embedding-scroll
path recomputes rag's internal blake2b prefix derivation by hand, a private
contract they hold under a sanctioned exception (their RCR-003) that breaks
silently if the derivation ever changes. Second, `server stop` rejects
`--json`, so a broker that drives `server start --json` and
`server status --json` hits an unparseable human-text outcome on the one
lifecycle verb that tears the service down.

## Considerations

- `service-domain-owns-operability`: one service-domain behavior, adapted by
  route, CLI, and MCP - never a parallel per-adapter lookup.
- The `2026-06-18-storage-lifecycle-adr` (D3/D8) already specified a `--root`
  survey filter; only the status filters shipped. A root-scoped lookup
  completes an accepted decision rather than opening a new one.
- The `2026-06-27-rag-broker-affordances-adr` shipped `server start --json`
  and explicitly named "a `server stop --json` sibling" as a pathway opened,
  with a codification candidate: broker-facing lifecycle verbs emit exactly
  one structured envelope on every exit path and treat already-satisfied as
  success.
- A filter alone cannot serve the dashboard: a root absent from the manifest
  (not yet indexed) would return nothing, and the caller would still need the
  hash. The lookup must return the authoritative computed prefix for the
  queried root regardless of manifest presence.
- `server stop` has six exit paths (research F7), all currently exit 0 -
  including the identity-unconfirmed skip where the service is left running.

## Considered options

- **O1 - survey `?root=` filter + computed `queried_root` (chosen).** Extends
  the existing read-only survey surface through all three adapters; unindexed
  roots still get the authoritative prefix. Completes storage-lifecycle D3/D8.
- **O2 - prefix field on `server status --json`.** Rejected: status is
  per-config lifecycle state; the dashboard asks about arbitrary roots, and a
  second classification surface would fork the survey's authority.
- **O3 - prefix on `/health`.** Rejected: health is identity/liveness and
  deliberately light; loading it with storage semantics couples liveness
  probing to storage classification.
- **O4 - export `root_collection_prefix()` as a public Python API.** Rejected
  as the primary fix: the dashboard consumes the service over HTTP, not the
  Python package; a library export would not serve non-Python consumers and
  still leaves the derivation exercised outside the service domain.
- **Stop skip-path exit code - align both modes at exit 1 (chosen)** over
  json-only divergence: a verb that leaves the service running did not do its
  job; hiding that behind exit 0 misleads scripts in either mode, and mode-
  dependent exit codes are a trap.

## Constraints

- The survey is server-mode only (local mode has a single namespace); the
  root lookup inherits that scope. The 409 non-server-mode contract is
  unchanged.
- The route is token-gated like every monitoring route; the lookup adds no
  new auth surface.
- `queried_root.prefix` must come from the one real derivation
  (`root_collection_prefix()` in `src/vaultspec_rag/store.py`), never a
  reimplementation - the whole point is a single authority.
- Stop `--json` must suppress all human/console output and emit exactly one
  envelope on stdout per exit path (broker contract from the
  rag-broker-affordances ADR).
- The human-mode exit-code change on the skip path (0 to 1) is a deliberate,
  documented behavior change; help text and tests must record it.

## Implementation

**Root-scoped survey lookup.** `GET /storage/survey` accepts an optional
`root` query parameter. The route resolves the parameter through
`root_collection_prefix()` and (a) narrows the namespace list to entries whose
prefix matches, and (b) adds a top-level `queried_root` object -
`{root: <resolved>, prefix: <r{12-hex}_>}` - present only when `root` was
passed. An unindexed root returns `queried_root` with an empty namespace list.
The serviceclient transport admits `root` into the survey params; the CLI
`server storage survey` gains `--root PATH` (rendered in both human and
`--json` output); the MCP `get_storage_survey` tool gains the optional `root`
argument. All three adapters pass the parameter through to the one route -
no adapter computes anything.

**Stop envelope parity.** `server stop` gains `--json`, mirroring start's
machinery: success envelopes `{ok: true, command: "service.stop", data: {status, ...}}` with statuses `stopped`, `already_stopped` (nothing to
stop - the idempotent success), `cleaned` (stale discovery file removed for a
confirmed-dead pid), and `reclaimed` (machine-singleton holder terminated);
failure envelope `{ok: false, command, error: "identity_unconfirmed", message, data}` with exit 1 when a live pid's identity cannot be confirmed
and the service is left running - in both `--json` and human mode. The
`--port` variant emits the same envelopes.

**Tests.** Integration: `?root=` for an indexed root (prefix + populated
namespaces), an unindexed root (prefix + empty list), and adapter
pass-through (CLI `--root`, MCP arg). Lifecycle: one envelope per stop exit
path with asserted exit codes, alongside the existing start `--json` matrix.

## Rationale

The survey is already the single read-only storage surface shared by route,
CLI, and MCP, and already reverse-maps prefixes through the persisted
manifest (research F2, F5); extending it keeps one classification authority
and completes what storage-lifecycle D3/D8 sanctioned (F3). Returning the
computed prefix for the queried root (F4) is what actually deletes the
dashboard's hand-rolled hash - a pure filter would leave the unindexed-root
case unserved. Stop `--json` was pre-approved as a pathway by the
rag-broker-affordances ADR (F6), and its envelope/idempotency contract is
lifted verbatim from that ADR's codification candidate; the skip path is the
one genuine failure among stop's six exits (F7) and must surface as one.

## Consequences

- **Gains.** The dashboard deletes its RCR-003 exception and re-sources the
  embedding scroll from the service; brokers get full lifecycle envelope
  parity (start/stop/status); the prefix derivation returns to a single
  authority inside the service domain.
- **Honest difficulties.** The skip-path exit-code change (0 to 1) can
  surprise existing scripts that treated any stop as exit 0; it is the
  correct contract but must be called out in the changelog. `queried_root`
  makes the survey response shape conditional - consumers must treat the
  field as optional.
- **Pathways opened.** The remaining unshipped D3/D8 filter (`--since`) has
  an established pattern; the broker-facing envelope rule candidate
  accumulates its second full execution cycle, maturing it toward promotion.
- **Pitfalls to avoid.** Reimplementing the hash anywhere outside
  `root_collection_prefix()`; emitting human text on a `--json` path;
  filtering by string-matching roots instead of resolving through the one
  derivation (case/resolution normalisation would silently diverge on
  Windows).

## Codification candidates

- **Rule slug:** `broker-facing-cli-outcomes-are-structured-and-idempotent`
  (second execution cycle; originated in the rag-broker-affordances ADR).
