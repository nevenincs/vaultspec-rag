---
tags:
  - '#adr'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-discovery-schema-research]]"
---

# `service-discovery-schema` adr: `version and document the service discovery file as a stable interface` | (**status:** `accepted`)

## Problem Statement

The resident RAG service writes a discovery file that sibling tools read to locate and
health-check it; the vaultspec engine's Rust RAG client is a known consumer. The file is an
undocumented, unversioned interface assembled across two writers at two timestamp precisions
(research F1-F4). GitHub issue **#190** records the consequence: a consumer that parsed the
heartbeat timestamp as an epoch number rejected the ISO-8601 string and reported the service
DOWN while it was UP, degrading every semantic-search-dependent feature. This ADR decides how
to turn the file into a documented, versioned, format-stable interface. It is grounded in
`2026-06-24-service-discovery-schema-research`. It is a contract-hardening decision on a
mature in-tree surface, not a new feature, and the consumer is separately being made to parse
defensively, so nothing is blocked on it - this is the durable fix.

## Considerations

- The file has two writers (research F1): the CLI parent's initial write and the daemon's
  heartbeat merge. The timestamp precision diverges between them (`started_at` microseconds,
  `last_heartbeat` seconds) - the direct cause of the breakage.
- There is no version discriminator (F2), no interface/internal field distinction (F3), and
  the staleness contract lives only in prose that can drift from the daemon's actual cadence
  (F4).
- The atomic write-to-`.tmp` + `os.replace` discipline and the heartbeat's additive
  read-merge-write are already correct (F5) and must be preserved by any change.
- The CLI status surface reads the current flat shape, so a schema change must not break that
  in-process reader.

## Constraints

- Back-compat: existing consumers (and the CLI status reader) read the current flat fields; a
  version field and a normalised timestamp must be additive, not a breaking re-layout, for v1.
- Two-writer consistency: the version discriminator and the timestamp format must be emitted
  identically by both the CLI-parent initial write and the daemon heartbeat, or the divergence
  simply moves.
- No frontier/library risk: stdlib `datetime`/`json` and the existing atomic-write helper;
  this is a small, well-understood change plus documentation.
- The schema document is a consumer-facing interface contract; once published, changing it
  requires a version bump, so the v1 field set must be chosen deliberately.

## Implementation

High-level; a plan sequences it.

**D1 - One declared timestamp format for both fields.** Normalise the CLI-parent `started_at`
write to ISO-8601 with offset at second precision (`timespec="seconds"`), matching the
heartbeat's `last_heartbeat`. Both timestamp fields then share one declared encoding
(ISO-8601 with offset, second precision). ISO-with-offset is kept over epoch because it is
already what both writers emit; the durable requirement is that the format is declared and
identical, which D1 makes true. (Resolves research open question 1.)

**D2 - A version discriminator emitted by both writers.** Add a `schema` string
(`vaultspec.rag.service`) and an integer `version` (starting at `1`) to the file. The
CLI-parent initial write sets them; the heartbeat merge preserves them (and re-asserts them so
a file written by an older parent is upgraded on the first tick). Consumers pin on
`(schema, version)` and detect change. (Resolves research open question 2.)

**D3 - A consumer-facing schema reference document.** Author a `reference` vault document that
names every interface field, its type and format, marks which fields are a stable interface
versus internal diagnostics (`executable`, `prefix`, `base_prefix`, `virtual_env` are
diagnostics, not interface), and states the staleness contract (heartbeat cadence, stale
threshold, PID-reuse caveat). The flat shape is retained - internal fields are documented as
non-interface rather than relocated - so the existing CLI status reader is untouched.
(Resolves research open question 3, lighter option.)

**D4 - Surface the staleness contract in the file, not only in prose.** Emit
`heartbeat_interval_s` and `stale_after_s` as fields so a consumer reads the liveness contract
from the file the daemon actually wrote rather than hard-coding a threshold from prose that can
drift. Sourced from the same config the heartbeat loop uses. (Resolves research open question
4; small and separable - if descoped, the contract is documentation-only in D3.)

**D5 - Regression coverage for the contract.** Tests assert: both writers emit the same
`(schema, version)` and the same timestamp format/precision for `started_at` and
`last_heartbeat`; the version is present after the CLI-parent write and preserved across a
heartbeat tick; the atomic-write discipline is intact. No mocks - exercise the real writers.

## Rationale

The breakage was a cross-tool contract gap, not a writer bug (research F6), so the fix is to
make the contract explicit and stable rather than to patch a code path. D1 removes the
specific divergence that broke the consumer; D2 gives consumers a pin point and a change
signal, matching vaultspec-core's enveloped-schema discipline; D3 is the single highest-value
item (the issue notes documentation alone would have prevented the breakage); D4 closes the
prose-drift hazard cheaply. ISO-with-offset over epoch is chosen because it is already emitted
and human-legible; the load-bearing property is "declared and identical", which D1 delivers.

## Consequences

- Gains: a versioned, documented, single-format discovery interface; consumers can pin and
  detect change; the timestamp divergence that caused the outage is gone; the liveness contract
  is machine-readable, not prose-only.
- Costs and risks: the schema document becomes a maintained interface contract - future field
  changes require a version bump and a doc update (this is the intended cost). Adding fields is
  additive and safe for existing readers; the only behavioural change is `started_at` precision
  shrinking to seconds, which a correct ISO parser tolerates.
- Pathways: a stable `(schema, version)` lets consumers negotiate behaviour by version and lets
  a future v2 evolve the shape without silently breaking readers.

## Codification candidates

- **Rule slug:** `discovery-file-is-a-versioned-interface`.
  **Rule:** The service discovery file is a consumer-facing interface: every field a sibling
  tool may read must be documented, carry a `(schema, version)` discriminator, use one declared
  timestamp format emitted identically by all writers, and any shape change must bump the
  version and update the schema document.

  *(Candidate only - promoted to a rule after the constraint has held across at least one full
  execution cycle, per the codify discipline.)*
