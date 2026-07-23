---
generated: true
tags:
  - '#index'
  - '#managed-log-contract'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - '[[2026-07-21-managed-log-contract-W01-P01-S01]]'
  - '[[2026-07-21-managed-log-contract-W01-P01-S02]]'
  - '[[2026-07-21-managed-log-contract-W01-P01-S03]]'
  - '[[2026-07-21-managed-log-contract-W01-P01-summary]]'
  - '[[2026-07-21-managed-log-contract-W01-P02-S04]]'
  - '[[2026-07-21-managed-log-contract-W01-P02-S05]]'
  - '[[2026-07-21-managed-log-contract-W01-P02-summary]]'
  - '[[2026-07-21-managed-log-contract-W02-P03-S06]]'
  - '[[2026-07-21-managed-log-contract-W02-P03-S07]]'
  - '[[2026-07-21-managed-log-contract-W02-P03-S08]]'
  - '[[2026-07-21-managed-log-contract-W02-P03-summary]]'
  - '[[2026-07-21-managed-log-contract-W02-P04-S09]]'
  - '[[2026-07-21-managed-log-contract-W02-P04-S10]]'
  - '[[2026-07-21-managed-log-contract-W02-P04-S11]]'
  - '[[2026-07-21-managed-log-contract-W02-P04-summary]]'
  - '[[2026-07-21-managed-log-contract-W02-P05-S12]]'
  - '[[2026-07-21-managed-log-contract-W02-P05-S13]]'
  - '[[2026-07-21-managed-log-contract-W02-P05-summary]]'
  - '[[2026-07-21-managed-log-contract-W03-P06-S14]]'
  - '[[2026-07-21-managed-log-contract-W03-P06-S15]]'
  - '[[2026-07-21-managed-log-contract-W03-P06-S16]]'
  - '[[2026-07-21-managed-log-contract-W03-P06-summary]]'
  - '[[2026-07-21-managed-log-contract-W03-P07-S17]]'
  - '[[2026-07-21-managed-log-contract-W03-P07-S18]]'
  - '[[2026-07-21-managed-log-contract-W03-P07-S19]]'
  - '[[2026-07-21-managed-log-contract-W03-P07-S20]]'
  - '[[2026-07-21-managed-log-contract-W03-P07-summary]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
  - '[[2026-07-21-managed-log-contract-audit]]'
  - '[[2026-07-21-managed-log-contract-plan]]'
  - '[[2026-07-21-managed-log-contract-reference]]'
  - '[[2026-07-21-managed-log-contract-research]]'
---

# `managed-log-contract` feature index

Auto-generated index of all documents tagged with `#managed-log-contract`.

## Documents

### adr

- `2026-07-21-managed-log-contract-adr` - `managed-log-contract` adr: `uniform bounded logs with clean-break operator contract` | (**status:** `accepted`)

### audit

- `2026-07-21-managed-log-contract-audit` - `managed-log-contract` audit: `managed logging implementation safety and intent review`

### exec

- `2026-07-21-managed-log-contract-W01-P01-S01` - Replace service-only retention settings and environment names with the generic managed-log contract
- `2026-07-21-managed-log-contract-W01-P01-S02` - Install the service log handler from the generic managed-log settings
- `2026-07-21-managed-log-contract-W01-P01-S03` - Assert generic defaults, environment overrides, and removal of legacy configuration names
- `2026-07-21-managed-log-contract-W01-P01-summary` - `managed-log-contract` `W01.P01` summary
- `2026-07-21-managed-log-contract-W01-P02-S04` - Implement bounded raw-byte rotation and configure the Qdrant supervisor from the shared retention policy
- `2026-07-21-managed-log-contract-W01-P02-S05` - Exercise real Qdrant-output rollover, retention, restart append, and diagnostic continuity
- `2026-07-21-managed-log-contract-W01-P02-summary` - `managed-log-contract` `W01.P02` summary
- `2026-07-21-managed-log-contract-W02-P03-S06` - Replace the legacy service-only reader with bounded source-aware grouped log retrieval
- `2026-07-21-managed-log-contract-W02-P03-S07` - Filter source-tagged groups without merging or fabricating chronology
- `2026-07-21-managed-log-contract-W02-P03-S08` - Verify sparse backup discovery, per-source limits, grouped output, and malformed-source rejection
- `2026-07-21-managed-log-contract-W02-P03-summary` - `managed-log-contract` `W02.P03` summary
- `2026-07-21-managed-log-contract-W02-P04-S09` - Serve source-aware plain and JSON log responses from the shared reader
- `2026-07-21-managed-log-contract-W02-P04-S10` - Carry the source selector and structured log outcome through the admin transport
- `2026-07-21-managed-log-contract-W02-P04-S11` - Verify authenticated live responses, bounds, filters, and source-group schema
- `2026-07-21-managed-log-contract-W02-P04-summary` - `managed-log-contract` `W02.P04` summary
- `2026-07-21-managed-log-contract-W02-P05-S12` - Replace the legacy activity parser and raw compatibility flag with grouped source rendering and offline fallback
- `2026-07-21-managed-log-contract-W02-P05-S13` - Update in-process CLI contract coverage for source selection and local post-crash reads
- `2026-07-21-managed-log-contract-W02-P05-summary` - `managed-log-contract` `W02.P05` summary
- `2026-07-21-managed-log-contract-W03-P06-S14` - Document generic managed-log environment variables and aggregate retention semantics
- `2026-07-21-managed-log-contract-W03-P06-S15` - Document source selection, grouped output, JSON shape, and removal of the raw flag
- `2026-07-21-managed-log-contract-W03-P06-S16` - Document live and post-crash service plus Qdrant log inspection
- `2026-07-21-managed-log-contract-W03-P06-summary` - `managed-log-contract` `W03.P06` summary
- `2026-07-21-managed-log-contract-W03-P07-S17` - Run focused unit and integration suites for configuration, writers, routes, transport, and CLI
- `2026-07-21-managed-log-contract-W03-P07-S18` - Run repository formatting, lint, type, and complete test gates required by project configuration
- `2026-07-21-managed-log-contract-W03-P07-S19` - Validate managed-log vault artifacts and feature index integrity
- `2026-07-21-managed-log-contract-W03-P07-S20` - Record formal safety, intent, and quality review findings
- `2026-07-21-managed-log-contract-W03-P07-summary` - `managed-log-contract` `W03.P07` summary

### plan

- `2026-07-21-managed-log-contract-plan` - `managed-log-contract` plan

### reference

- `2026-07-21-managed-log-contract-reference` - `managed-log-contract` reference: `current log ownership, Qdrant 1.18.2, and operator paths`

### research

- `2026-07-21-managed-log-contract-research` - `managed-log-contract` research: `bounded multi-source logging and clean-break operator contract`
