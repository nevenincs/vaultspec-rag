---
tags:
  - '#adr'
  - '#server-watch-observability'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - "[[2026-07-29-server-watch-observability-research]]"
  - '[[2026-07-29-server-watch-observability-reference]]'
  - '[[2026-07-27-jobs-tui-adr]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
---

# `server-watch-observability` adr: `one server watch console for indexing, search, and managed logs` | (**status:** `accepted`)

## Problem Statement

The root watch surface presents one operational lane of a two-lane service. Index jobs
have retained state and controls, while served searches have neither active/recent state
nor a query review surface. Its only log view is a selected-job transformation over a
small service-only snapshot, not the managed service and Qdrant pool. The result is a
screen named for the server that cannot review what the server is serving or what its
two managed producers actually recorded. The implementation evidence and existing
contract boundaries are recorded in `2026-07-29-server-watch-observability-research`
and `2026-07-29-server-watch-observability-reference`.

## Considerations

- The accepted jobs interface owns terminal lifecycle, responsive layout, controls, and
  a bounded per-job log inspection mode (`2026-07-27-jobs-tui-adr`).
- The accepted managed-log contract owns grouped raw service and Qdrant records, bounds,
  rotation, filters, and visible truncation; it explicitly does not infer a cross-source
  chronology (`2026-07-21-managed-log-contract-adr`).
- Health, jobs, logs, and search diagnostics are service-domain behavior adapted by
  entry points, so query activity cannot be invented inside the TUI
  (`2026-06-01-service-observability-adr`).
- Search query text is operationally necessary and potentially sensitive; its retention
  need not equal durable metadata retention
  (`2026-07-29-server-watch-observability-research`).
- A root server monitor and a job-focused invocation must not become two implementations
  of jobs rendering, polling, controls, or terminal ownership
  (`2026-07-29-server-watch-observability-reference`).

## Considered options

- One canonical server-watch application over job, search-activity, and managed-log
  domains is chosen. Wide layouts show indexing and search simultaneously; narrow
  layouts preserve both lane counts and switch lanes without losing state.
- A second server-monitor application beside the jobs application is rejected because
  it duplicates terminal and jobs behavior and will drift.
- Deriving query review by parsing `service.search` log lines is rejected because logs
  do not represent every active and terminal branch, and persisting query text expands
  the privacy boundary.
- Merging service and Qdrant records into a timestamp-sorted global chronology is
  rejected because the producers do not share a trustworthy clock or record dialect.
- An unbounded event stream or database-backed query audit is rejected because this is a
  live bounded operator surface, not a compliance archive.

## Constraints

- The existing jobs and managed-log contracts are stable accepted parents and remain the
  concrete owners of their current behavior. This decision extends rather than replaces
  their bounds, controls, source identity, or terminal handoff.
- `server --watch` and `server jobs --watch` use one concrete application. The former
  opens the complete server monitor; the latter selects jobs-focused mode. No old class
  alias, forwarding wrapper, or compatibility re-export survives a rename.
- Search activity is bounded and filterable in the service domain. It contains an active
  map plus a finite recent-terminal ring and covers success, partial success,
  unavailability, validation rejection, admission failure, unexpected exception, and
  cancellation.
- Every admitted request gets one stable request id and exactly one terminal ledger
  transition. Cleanup runs from a lifecycle boundary that cannot omit an exception path.
- Full query text is held only in the bounded in-memory ledger and returned only through
  the existing token-gated loopback admin boundary. Persistent structured logs omit
  query text and result bodies.
- Global logs use the canonical `all` source read at its existing record and byte caps.
  Service and Qdrant groups remain separate, and origin plus truncation metadata is
  always visible.
- Raw display means one sanitized input record rendered once. Terminal escape and control
  sanitization remains mandatory; parsing, repacking, elision, and noise suppression are
  opt-in and cannot silently alter the default review.
- The search pool is rendered with encode and index pool state.
- No implementation or verification step may launch the resident service, initialize
  compute, run a live/GPU test, or attempt degraded semantic-search recovery.
- Tests import production owners and use real records, real managed files, real
  concurrency, and Textual's real pilot. Fakes, mocks, stubs, patches, monkeypatches,
  skips, xfails, and mirrored business logic are forbidden.

## Implementation

Introduce a service-owned `SearchActivityLedger` with typed request snapshots and
thread-safe start/finish operations. The search route starts a record after request
identity is assigned, updates it once on every terminal path, and continues to emit
metadata-only structured completion events. A bounded authenticated read route and the
canonical service client expose active/recent requests with limit, state, search type,
root, request-id, and since filters. Snapshots carry query text, request type, root,
top-k, state, timestamps, duration, status, result count, error classification, and
phase timings; they never carry result bodies.

Rename the terminal owner to `ServerWatchApp` and migrate callers and tests directly.
It concurrently polls the jobs projection, search activity, server status, and managed
logs without allowing older responses to overwrite newer generations. Wide composition
shows jobs and searches side by side. Narrow composition switches them through one
responsive layout while both counts and activity indicators remain visible. Search
selection opens request detail; job selection retains the existing job-control and
per-job inspection behavior.

Add a full-height global log view that polls the existing grouped `all` managed-log
response at the canonical caps. It renders source headers, raw sanitized records, and
bounds/truncation markers without hidden filters by default. The parsed job-log view
remains an explicit focused inspection tool rather than the global source of truth.

The acceptance boundary is observable: concurrent index and search activity are both
visible on the root screen; active searches transition once to terminal rows; every
terminal branch is counted; service and Qdrant records appear under their own sources;
no default raw record disappears or is repacked; narrow layout preserves access to both
lanes; search-pool pressure is rendered; and query text never appears in retained
managed logs.

## Rationale

Only a service-owned ledger can show a query while it is running and guarantee a
terminal outcome across all route branches. Only the managed-log owner can define
retention, source identity, and truncation honestly. Adapting both from one terminal
owner therefore closes the two blind spots without duplicating domain behavior or
inventing a false event chronology. The memory-versus-log privacy split preserves actual
local query review while making accidental durable disclosure a failed design rather
than a rendering preference (`2026-07-29-server-watch-observability-research`).

## Consequences

The root watch screen becomes an actual resident-service monitor and represents indexing
and search as equal operational lanes. The same bounded search truth becomes available
to CLI and programmatic admin clients, and global logging review finally includes both
managed producers.

The search path gains a small lock-protected state write at admission and completion.
Every newly added route return must preserve exactly-once terminal accounting. Query
text remains present in process memory for the configured recent window and is visible
to any caller holding the local admin token; operators must treat that token accordingly.

Polling four domains increases local monitoring traffic. Each poll remains bounded,
generation-ordered, and independently degradable so a log or search-activity read cannot
freeze job controls. The global log tank is not an audit archive, and rotation can evict
older records. Source grouping means operators must correlate service and Qdrant records
by request evidence rather than by an invented unified order.

The old jobs-only application symbol and unreachable genuine-Qdrant parsing assumptions
are removed. Downstream imports and tests must move to the concrete owner in the same
change.
