---
tags:
  - '#research'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---

# `service-discovery-schema` research: `documenting and versioning the service discovery file`

The resident RAG service writes a discovery file that sibling tools read to locate and
health-check the service - notably the vaultspec engine's Rust RAG client. The file's field
set, timestamp format, staleness semantics, and stability across versions are all
undocumented and unversioned. GitHub issue **#190** reports a concrete breakage: a consumer
parsing the heartbeat timestamp as an epoch number rejected the ISO-8601 string and reported
the service DOWN while it was UP, spuriously degrading every semantic-search-dependent
feature. This research characterises the file as it is written today and weighs the options
for turning it into a documented, versioned, consumer-facing interface. It feeds an ADR. No
implementation is proposed here. (The engine consumer is separately being made to parse
defensively, so nothing is blocked on this work - it is the durable fix.)

## Findings

### F1 - Two writers produce the file, at two different timestamp precisions

The discovery file is not written by one author. The CLI parent writes it once at start with
the initial identity, and the daemon's heartbeat task merges fields on every tick:

- The CLI-parent initial write (`_write_service_status`) sets `started_at` with a plain
  `datetime.now(UTC).isoformat()` - **microsecond** precision.
- The daemon heartbeat (`_heartbeat_tick_sync`) sets `last_heartbeat` with
  `isoformat(timespec="seconds")` - **second** precision - and additively merges `pid`,
  `parent_pid`, the supervised `qdrant_pid`/`qdrant_alive`/`qdrant_port`, and the
  per-process `service_token`.

So the two timestamps are both ISO-8601 with offset but differ in precision, and the field
set is assembled across two code paths. This split is the direct source of the precision
divergence the consumer hit (issue #190's observed `started_at` microseconds vs
`last_heartbeat` seconds).

### F2 - There is no schema or version field

Nothing in the file declares what schema it conforms to or what version it is. A consumer
cannot pin to a known shape or detect a format change; it can only parse defensively and hope.
This is out of step with the sibling vaultspec-core convention of enveloped, versioned schemas
(e.g. a `vaultspec.rag.service.v1`-style discriminator).

### F3 - Interface and internal fields are undistinguished

The file mixes fields a consumer legitimately needs (`pid`, `port`, `started_at`,
`last_heartbeat`, `service_token`, the qdrant pair) with fields that are clearly internal
process detail (`executable`, `prefix`, `base_prefix`, `virtual_env`). Nothing marks which
fields are a stable interface versus incidental diagnostics, so a consumer cannot tell what
it may rely on.

### F4 - Staleness semantics live only in prose

The heartbeat cadence and stale threshold (documented elsewhere as roughly a 15s heartbeat and
a 60s stale window) are stated in prose, not adjacent to the file or in any machine-readable
form. A consumer deciding "is this service alive?" must hard-code a threshold inferred from
documentation that can drift from the cadence the daemon actually uses, and must also account
for the PID-reuse caveat (a recorded PID may belong to an unrelated process after a crash).

### F5 - The atomic-write discipline is already correct and must be preserved

Both writers go through a write-to-`.tmp` + `os.replace` swap, so a reader never observes a
half-written file. The heartbeat read-merge-write is also resilient (missing file -> exit,
unparseable -> debug-log and skip). Any schema change (adding a version field, normalising
timestamps) must keep this atomic, additive-merge discipline; it is not a defect to fix but a
property to retain.

### F6 - The breakage is a contract gap, not a bug in the writer

The writer is internally consistent for its own consumers (the CLI status surface reads it
fine). The failure is purely at the cross-tool boundary: an undocumented, unversioned,
two-precision interface met a consumer that guessed wrong about the timestamp encoding. The
fix is therefore a *contract* fix - document it, version it, make the format stable and
single - not a code defect repair.

## Options weighed (for the ADR)

- **Timestamp format (the load-bearing choice).** Option A: ISO-8601 with offset at one
  stated precision for *both* writers (normalise the CLI-parent `started_at` to match the
  heartbeat's `timespec="seconds"`, or pick a single precision for both). Option B: epoch
  integer/float (e.g. epoch-ms) for both. ISO-with-offset is recommended for human
  readability and because it is already what both writers emit (the change is only to unify
  precision); the durable requirement is that the format is *declared and identical across
  both fields*, whichever is chosen.
- **Versioning.** Add a `schema`/`version` discriminator (e.g. a `schema` string plus an
  integer `version`), mirroring vaultspec-core's enveloped-schema discipline, so consumers can
  pin and detect change. Low cost, high durability.
- **Documentation surface.** A consumer-facing schema document (one section) naming every
  interface field, its type and format, the staleness contract, and which fields are interface
  versus internal diagnostics. Per the issue, item 1 (documentation) alone would have
  prevented the breakage; items 2-4 (stable timestamp, version field, staleness semantics) are
  cheap and make the contract durable.
- **Interface vs internal fields.** Either document the internal fields as explicitly
  non-interface, or group them under a clearly-named sub-key; the lighter documentation-only
  option is likely sufficient and avoids breaking the CLI status reader that consumes the flat
  shape today.

## Open questions for the ADR

- Confirm the timestamp encoding (ISO-with-offset at a fixed precision vs epoch) and the exact
  precision, applied to both `started_at` and `last_heartbeat`.
- Confirm the version discriminator shape (`schema` string + integer `version`, or a single
  `vaultspec.rag.service.v1`-style string) and the starting value.
- Decide whether internal fields are documented-as-non-interface or relocated under a sub-key
  (and whether relocation would break the existing CLI status reader, which reads the flat
  shape).
- Decide where the schema document lives (a `reference` vault document versus a user-facing
  docs page) and whether the staleness contract is also surfaced in the file (e.g. a
  `heartbeat_interval_s`/`stale_after_s` pair) rather than prose only.
