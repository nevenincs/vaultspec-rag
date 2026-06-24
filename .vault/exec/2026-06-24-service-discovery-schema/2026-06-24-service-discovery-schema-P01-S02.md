---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S02'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---

# Emit the schema string and integer version discriminator in the CLI-parent initial discovery-file write

## Scope

- `src/vaultspec_rag/cli/_service_status.py`

## Description

- Emitted the `schema` (`vaultspec.rag.service`) and integer `version` (1) discriminator in the CLI-parent initial discovery-file write.

## Outcome

Every freshly written discovery file now carries a pinnable `(schema, version)` from the first write.

## Notes

No incidents; no scaffolds left in code.
