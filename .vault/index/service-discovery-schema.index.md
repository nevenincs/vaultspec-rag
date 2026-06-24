---
generated: true
tags:
  - '#index'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - '[[2026-06-24-service-discovery-schema-P01-S01]]'
  - '[[2026-06-24-service-discovery-schema-P01-S02]]'
  - '[[2026-06-24-service-discovery-schema-P01-S03]]'
  - '[[2026-06-24-service-discovery-schema-P01-S04]]'
  - '[[2026-06-24-service-discovery-schema-P02-S05]]'
  - '[[2026-06-24-service-discovery-schema-P03-S06]]'
  - '[[2026-06-24-service-discovery-schema-P03-S07]]'
  - '[[2026-06-24-service-discovery-schema-adr]]'
  - '[[2026-06-24-service-discovery-schema-audit]]'
  - '[[2026-06-24-service-discovery-schema-plan]]'
  - '[[2026-06-24-service-discovery-schema-research]]'
---

# `service-discovery-schema` feature index

Auto-generated index of all documents tagged with `#service-discovery-schema`.

## Documents

### adr

- `2026-06-24-service-discovery-schema-adr` - `service-discovery-schema` adr: `version and document the service discovery file as a stable interface` | (**status:** `accepted`)

### audit

- `2026-06-24-service-discovery-schema-audit` - `service-discovery-schema` audit: `discovery-file schema/version/timestamp contract review (PASS)`

### exec

- `2026-06-24-service-discovery-schema-P01-S01` - Normalise the CLI-parent initial write of started_at to ISO-8601 with offset at second precision, matching the heartbeat last_heartbeat format
- `2026-06-24-service-discovery-schema-P01-S02` - Emit the schema string and integer version discriminator in the CLI-parent initial discovery-file write
- `2026-06-24-service-discovery-schema-P01-S03` - Preserve and re-assert the schema, version, and staleness fields in the daemon heartbeat additive merge
- `2026-06-24-service-discovery-schema-P01-S04` - Emit heartbeat_interval_s and stale_after_s from the same config the heartbeat loop uses so the liveness contract is machine-readable
- `2026-06-24-service-discovery-schema-P02-S05` - Author the consumer-facing discovery-file schema document naming interface fields, marking internal diagnostics as non-interface, and stating the staleness and PID-reuse contract
- `2026-06-24-service-discovery-schema-P03-S06` - Add a no-mock test asserting both writers emit the same schema and version and the same timestamp format and precision for started_at and last_heartbeat
- `2026-06-24-service-discovery-schema-P03-S07` - Add a no-mock test asserting the version is present after the CLI-parent write and preserved across a heartbeat tick, with the atomic-write discipline intact

### plan

- `2026-06-24-service-discovery-schema-plan` - `service-discovery-schema` plan

### research

- `2026-06-24-service-discovery-schema-research` - `service-discovery-schema` research: `documenting and versioning the service discovery file`
