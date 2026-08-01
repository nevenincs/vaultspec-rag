---
tags:
  - '#research'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:0af6a932970a15ff57583ff7b8f209fdc21b4feeaa712d5e922f48836a2e7da0'
related:
  - "[[2026-07-21-managed-log-contract-reference]]"
  - "[[2026-04-12-store-eviction-log-rotation-research]]"
  - "[[2026-06-24-service-hardware-singleton-research]]"
---

# `managed-log-contract` research: `bounded multi-source logging and clean-break operator contract`

This research reconciles the accepted service-log rotation, service observability, and
Qdrant supervision decisions after live inspection showed that their ownership boundaries
do not form one managed logging contract. It compares the viable replacement shapes and
records the approved preference for a clean break without compatibility code. Detailed code
and upstream-source locators live in the linked `managed-log-contract` reference.

## Findings

### F1 - The resident service bounds only its own log

The service owns a Windows-aware rotating handler with a 10 MiB threshold and five backups.
The active file plus five generations has a 60 MiB default bound. The config names, handler
installation, rotated-set reader, HTTP routes, and CLI all describe this as the service log.
The accepted `store-eviction-log-rotation` decision intentionally solved only
`service.log`.

### F2 - The Qdrant capture decision created an append-only sibling

The later hardware-singleton decision requires supervised Qdrant stdout and stderr to reach
`qdrant.log` so a panic or bind failure remains diagnosable. The service's pipe-drain thread
meets that requirement but opens the same file in append mode for each child and restart. It
has no size threshold, backup count, or rollover. The 50-line recent-output ring is an
independent memory bound and does not limit persistent history.

This is omitted scope rather than conflict with an accepted append-forever decision. The
rotation ADR predates the Qdrant file, and the singleton ADR decides capture but not
retention.

### F3 - Qdrant cannot take back rotation ownership

Qdrant 1.18.2 emits operational logs to stdout by default. Its optional native disk logger
is append-only and explicitly warns that the file may grow indefinitely. Qdrant audit logs
do rotate, but they record a different compliance stream and do not preserve startup,
storage, or panic output.

Vaultspec must retain the supervised pipe and rotate at the pipe-drain boundary it already
owns. Enabling Qdrant's disk logger would duplicate the stream and add another unbounded
file.

### F4 - Every public reader omits Qdrant

The shared HTTP routes and `server logs` command terminate at the service-only rotated-set
reader. They expose no source selector and have no Qdrant branch. The CLI also requires a
reachable daemon, which hides retained logs after a crash or failed start.

A raw merge is not a valid correction. Service output includes Python records, Rich
multiline rendering, progress bars, and access lines. Qdrant uses RFC 3339 timestamps and
Rust logger names. The existing human parser rejects those timestamps, and a retrieval-time
sort cannot assign reliable timestamps to every multiline record.

### F5 - The existing rotated-set reader is not a reusable foundation

The reader discovers sequential backup suffixes and stops at the first missing number. The
live status directory contained `.1`, `.3`, and `.5`, so the reader silently omitted the
latter two generations. It also reads each whole file before taking a tail. A generalized
reader must enumerate numeric backups without assuming continuity and must bound both
searched history and returned output.

### F6 - The configuration and adapter names preserve the split

Keeping `service_log_max_bytes`, `service_log_backup_count`, `read_service_log`, and a
`service.logs` payload while extending their behavior would encode the obsolete ownership
model. Aliases or translation shims would make the replacement contract harder to reason
about and test. The owner approved a clean break: generic managed-log configuration and
source-aware outputs replace the old names and shapes directly.

## Considered options

### Keep the split contract

Reject. It leaves disk growth unbounded and makes Qdrant history inaccessible through the
operator surface.

### Add Qdrant rollover only

Reject as incomplete. It fixes disk retention but preserves the service-only reader,
online-only CLI, incompatible parser, and misleading configuration ownership.

### Merge both producers into `service.log`

Reject. It removes source identity, couples unlike rollover mechanics, adds Python prefixes
to raw child diagnostics, and still cannot produce a trustworthy cross-source chronology.

### Keep separate files under one managed contract

Choose. Each producer keeps a source-native file and rotating sink. One per-source policy,
one bounded reader abstraction, and source-tagged adapters make their lifecycle uniform
without pretending their records share one format.

## Recommended direction

- Replace the service-only size and backup settings with `managed_log_max_bytes` and
  `managed_log_backup_count`. Apply the same values independently to service and Qdrant.
  Preserve the existing 10 MiB and five-backup defaults. Do not add aliases for the removed
  keys.
- Give the Qdrant drain a raw rotating sink that closes its sole handle, rotates numbered
  backups, and securely reopens before continuing. Keep the recent-output ring independent.
- Replace `read_service_log` with a service-domain reader whose sources are `service`,
  `qdrant`, and `all`. Enumerate sparse numeric backups, search a bounded window per source,
  and return bounded source groups.
- Make `all` the default operator view. Render Service and Qdrant as separate source-tagged
  groups rather than merging by inferred timestamp. Source filters narrow the view.
- Use the same reader contract behind authenticated live HTTP and local offline CLI access.
  Remove service-only payload, command-envelope, reader, and parser compatibility paths.
- Verify the behavior with production imports and real processes. Cover both sinks, restart,
  pre-existing oversized files, sparse generations, filters, live routes, and stopped-service
  reads without mocks, patches, stubs, monkeypatches, skips, or xfails.

## Boundaries

- This decision does not introduce Qdrant's separate audit-log facility.
- It does not synthesize global record chronology.
- It does not restore logs to the public MCP surface removed by the accepted search-scope
  decision.
- It defers relocation of Qdrant history into the machine-global singleton directory. The
  managed sources remain under the configured status directory in this change.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
