---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:09a432278fa8f605f22bba62a6491eb86ff16178114bce41a94b9a563d76dfda'
step_id: 'S17'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add the document collection, payload indexes, schema-version contract, descriptor entry, and direct-consumer compatibility behavior

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Define the document collection name, payload fields, indexes, and ID scheme.
- Advertise document vectors and payload schema in the storage descriptor.
- Advance the schema generation and add opt-in domain requirements to compatibility checks.

## Outcome

Storage schema version 2 advertises an independently addressable document
collection. Older consumers fail safely on the newer generation, while newer
consumers can detect an older descriptor that lacks the required document domain.

## Notes

Formatting, lint, type checks, descriptor serialization, version refusal, and
required-domain compatibility probes passed.
