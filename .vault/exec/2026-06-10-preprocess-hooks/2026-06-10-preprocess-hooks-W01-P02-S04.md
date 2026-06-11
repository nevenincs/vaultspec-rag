---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S04'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Define PreprocOutput, PreprocUnit, and Locator models with extra=forbid, the units/text XOR validator, and the schema-version gate (D4, D5)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`

## Description

Added `_preprocess_schema.py`: pydantic v2 `PreprocOutput` (schema_version, preprocessor_id
/version, source_path, units XOR text, metadata), `PreprocUnit` (text, title, section,
anchor, locator, metadata), and `Locator` (kind, value int|str, optional end). All models
set `extra="forbid"`; a model validator enforces the units/text XOR and non-empty units
(D4). `validate_preproc_output()` runs `model_validate` then gates against
`SUPPORTED_SCHEMA_VERSION = 1`, raising `UnsupportedSchemaVersionError` for newer
documents (D5). `metadata` values are `pydantic.JsonValue` for lossless payload/JSON
round-trip.

## Outcome

Module complete; ruff clean, basedpyright strict 0. Torch-free (pydantic only).

## Notes

The internal embed path stays on the existing dataclasses; conversion happens at the W03
ingest seam.
