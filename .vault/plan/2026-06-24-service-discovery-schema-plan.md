---
tags:
  - '#plan'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
tier: L2
related:
  - '[[2026-06-24-service-discovery-schema-adr]]'
---


# `service-discovery-schema` plan

### Phase `P01` - Versioning and timestamp normalisation

Make both writers emit one declared timestamp format and a (schema, version) discriminator, and surface the staleness contract in the file.

- [x] `P01.S01` - Normalise the CLI-parent initial write of started_at to ISO-8601 with offset at second precision, matching the heartbeat last_heartbeat format; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `P01.S02` - Emit the schema string and integer version discriminator in the CLI-parent initial discovery-file write; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `P01.S03` - Preserve and re-assert the schema, version, and staleness fields in the daemon heartbeat additive merge; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P01.S04` - Emit heartbeat_interval_s and stale_after_s from the same config the heartbeat loop uses so the liveness contract is machine-readable; `src/vaultspec_rag/server/_lifecycle.py`.

### Phase `P02` - Consumer-facing schema documentation

Document the discovery file as a stable interface: interface fields, internal diagnostics, and the staleness contract.

- [x] `P02.S05` - Author the consumer-facing discovery-file schema document naming interface fields, marking internal diagnostics as non-interface, and stating the staleness and PID-reuse contract; `docs/service-discovery.md`.

### Phase `P03` - Regression coverage

Prove both writers agree on format and version and that the version survives a heartbeat tick, with no mocks.

- [x] `P03.S06` - Add a no-mock test asserting both writers emit the same schema and version and the same timestamp format and precision for started_at and last_heartbeat; `src/vaultspec_rag/tests/test_service_discovery_schema.py`.
- [x] `P03.S07` - Add a no-mock test asserting the version is present after the CLI-parent write and preserved across a heartbeat tick, with the atomic-write discipline intact; `src/vaultspec_rag/tests/test_service_discovery_schema.py`.

## Description

Turn the resident service's discovery file into a documented, versioned, format-stable
interface, per the ADR. The file is assembled by two writers - the CLI-parent initial write
and the daemon heartbeat merge - at two timestamp precisions, which is what broke a consumer
that parsed the heartbeat as an epoch number. Phase P01 unifies the timestamp format across
both writers, adds a `(schema, version)` discriminator emitted by both, and surfaces the
staleness contract as machine-readable fields. Phase P02 documents the file as a
consumer-facing interface, marking internal diagnostics as non-interface and stating the
staleness and PID-reuse contract, while keeping the flat shape so the existing CLI status
reader is untouched. Phase P03 proves the two writers agree and the version survives a
heartbeat tick, with no mocks. Grounded in the ADR and its research; this is the planning
artifact only, and the ADR awaits user sign-off before execution.

## Steps







## Parallelization

P01 (the writer changes) is the foundation: P03's tests assert the behaviour P01 establishes,
so P01 lands first. P02 (documentation) can be authored in parallel with P01 since the schema
it documents is fixed by the ADR, but it should be reconciled against the final field names
P01 emits before it is considered done. Within P01, S01-S04 touch two files and are
independent edits that can be made together; S03 (heartbeat preserve) is the natural pair to
S02 (parent emit) and they should be reviewed together so the two writers stay consistent.

## Verification

The plan is complete when every Step is closed and all of the following hold:

- Both `started_at` and `last_heartbeat` are emitted in one declared format - ISO-8601 with
  offset at second precision - by both the CLI-parent write and the daemon heartbeat.
- The discovery file carries a `schema` string and an integer `version`, written by the
  CLI-parent and preserved (and re-asserted) across heartbeat ticks.
- `heartbeat_interval_s` and `stale_after_s` are present and match the config the heartbeat
  loop uses.
- A consumer-facing schema document names every interface field, its type and format, marks
  the internal diagnostics as non-interface, and states the staleness and PID-reuse contract;
  the existing CLI status reader still reads the file unchanged.
- The regression tests pass against the real writers with no mocks, stubs, or skips, and the
  atomic write-to-`.tmp` + `os.replace` discipline is asserted intact; `ruff` and the type
  checker report zero violations.
