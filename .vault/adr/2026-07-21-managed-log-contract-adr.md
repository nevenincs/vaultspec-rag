---
tags:
  - '#adr'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:b176709031ca1b38c9a69071078f14f54614742825df6b384824950b75f6cd55'
related:
  - "[[2026-07-21-managed-log-contract-research]]"
  - "[[2026-07-21-managed-log-contract-reference]]"
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-01-service-observability-adr]]"
---

# `managed-log-contract` adr: `uniform bounded logs with clean-break operator contract` | (**status:** `accepted`)

## Problem Statement

The resident service has two operational-log producers but only one managed lifecycle.
`service.log` rotates at 10 MiB with five backups, while the supervised Qdrant child's
stdout and stderr append forever to `qdrant.log`. The HTTP and CLI log paths read only the
service generations, and the CLI cannot read either source after the daemon stops.

The split arose from two sound but incomplete decisions. The service-log rotation ADR
predates `qdrant.log`; the hardware-singleton ADR later required Qdrant panic capture but did
not decide retention or operator retrieval. The observability ADR then defined a
service-only rotated-set reader. Together they leave disk growth, source visibility, and
post-crash diagnosis inconsistent.

This ADR establishes one managed-log contract for the resident service and its supervised
Qdrant child. It replaces only the log-specific clauses of those parent decisions. Their
store eviction, machine-singleton, verified-attach, route gating, and other observability
decisions remain accepted.

## Considerations

- A managed source is either the resident service or its supervised Qdrant child. Each source
  keeps a distinct file because their formats, write mechanics, and diagnostic roles differ.
- Service-domain ownership means one internal retention and reader contract feeds HTTP and
  CLI adapters. The CLI may invoke that behavior locally when no daemon is reachable; it
  must not reimplement reader semantics.
- A bounded operator view caps both the history searched for filters and the records returned.
  An on-disk bound alone does not make an unbounded response safe.
- Qdrant's recent-output deque remains separate from persistent retention. Startup failures
  still need an immediate child-output tail even when rollover occurs.
- Windows rollover differs by producer. The service handler must rebind inherited stdout and
  stderr file descriptors. The Qdrant drain owns one handle and can close, rotate, and reopen
  it without service-style `dup2` behavior.
- A clean break removes obsolete names and payloads without aliases, translation shims,
  deprecation branches, or dual test matrices.
- Qdrant 1.18.2 cannot own this policy. Its optional operational file sink is also append-only;
  its rotating audit log is a different data stream.

## Considered options

- **Keep the split contract.** No implementation cost, but Qdrant remains unbounded and
  inaccessible through the operator surface. Rejected.
- **Add Qdrant rollover only.** Bounds disk usage with a small patch, but preserves misleading
  service-only configuration, online-only retrieval, and incompatible rendering. Rejected as
  incomplete.
- **Merge both producers into one file.** Reuses the service handler and produces one tail,
  but destroys source identity, couples unlike rollover mechanics, and cannot create reliable
  chronology from multiline and differently timestamped records. Rejected.
- **Keep separate files under one source-aware contract.** Preserves native diagnostics while
  applying uniform retention and retrieval semantics. Chosen.

## Constraints

- Apply the same size and backup values independently to each source. The policy is per source,
  not a shared byte pool.
- Preserve the existing 10 MiB and five-backup defaults. With two active files and ten total
  backups, the default aggregate ceiling is approximately 120 MiB.
- Keep rollover cross-platform, owner-safe, and resistant to symlink substitution. A failed
  rollover must not leave the Qdrant pipe undrained or service stdout bound to a discarded
  file.
- Discover rotated generations by numeric suffix without assuming contiguity. Readers must
  tolerate files that disappear during rollover.
- Return `all` as source groups. Do not infer global ordering from incompatible timestamps or
  from records without timestamps.
- Keep filtered searches and returned tails bounded per source. Empty matches remain successful
  bounded results, not evidence that a source was unavailable.
- Do not restore logs to the public MCP surface. The accepted MCP search-scope decision remains
  authoritative.
- The parent rotation, singleton, and observability features are stable and shipped. This ADR
  changes their log configuration and retrieval clauses only; it does not supersede the parent
  records as a whole.

## Implementation

We will replace `service_log_max_bytes` and `service_log_backup_count` with
`managed_log_max_bytes` and `managed_log_backup_count`. Their environment variables follow
the same generic naming. The old keys are invalid; no aliases or migration code will remain.

The service retains its specialized daemon rotating handler but reads the generic policy.
The Qdrant drain gains a raw rotating sink that owns its one file handle, checks the active
size before a write, closes before rollover, shifts bounded backups, and securely reopens.
The in-memory recent-output ring continues to receive every child line independently of
persistent-write success.

A source-aware service-domain reader replaces `read_service_log`. Its first-class sources are
`service`, `qdrant`, and `all`. It enumerates sparse numbered generations, reads them in source
order, applies bounded filters, and returns bounded source groups. `all` is the default and
keeps Service and Qdrant separate rather than merging their records.

The token-gated live HTTP routes expose the same source values and grouped JSON contract.
`server logs` uses the live route when the daemon is reachable and invokes the same
service-domain reader locally when it is not. Human output renders labeled source sections;
JSON preserves those groups. The service-only activity parser, payload shape, reader name,
configuration names, and error-handling branches are removed.

Real-behavior verification covers both rotating sinks, restart continuity, pre-existing
oversized files, sparse backup generations, bounded filtering, authenticated live reads, and
local post-crash reads. Tests import production code and use real files and processes without
fakes, mocks, stubs, patches, monkeypatches, skips, or xfails.

## Rationale

The managed-log research found that retention, source selection, rendering, and offline access
share one ownership defect: each layer assumes `service.log` is the complete operational log.
Fixing only the Qdrant writer would leave that assumption intact. The linked reference also
shows why neither Qdrant's native file logger nor a raw one-file merge can satisfy the
diagnostic and cross-platform constraints.

Separate sources under one service-domain contract remove the structural mismatch without
discarding useful raw output. Generic configuration names make the ownership model truthful.
Grouped output avoids fabricated chronology. Local use of the same reader makes crash
diagnosis available without creating a second behavior implementation.

The owner explicitly rejected backwards-compatibility code. A direct replacement therefore
has a lower long-term cost than aliases whose only purpose would be to preserve the obsolete
service-only model.

## Consequences

- Both operational sources receive a finite, predictable disk bound. Qdrant request and panic
  output can no longer grow forever.
- Operators get the same source selection, filtering, raw fidelity, and JSON grouping through
  live HTTP and post-crash CLI paths.
- Configuration and output contracts break deliberately. Existing deployments using the old
  service-log keys must adopt the new names, and scripts consuming the old service-only JSON
  payload must adopt source groups.
- The default aggregate log budget doubles from approximately 60 MiB to 120 MiB because each
  source receives an independent active file and five backups.
- Source grouping is honest but not a single chronological incident timeline. Future structured
  ingestion could add a shared timestamp envelope without changing file ownership.
- Qdrant log relocation into the machine-global singleton directory remains deferred. This ADR
  manages both sources under the configured status directory.
- The implementation must update generated command help and configuration reference material;
  the ADR itself is not an operator how-to guide.
