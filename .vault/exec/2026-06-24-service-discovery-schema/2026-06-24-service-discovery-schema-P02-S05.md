---
tags:
  - '#exec'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S05'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---




# Author the consumer-facing discovery-file schema document naming interface fields, marking internal diagnostics as non-interface, and stating the staleness and PID-reuse contract

## Scope

- `docs/service-discovery.md`

## Description

- Authored the consumer-facing discovery-file schema document: interface fields with types/formats, the version discriminator, the staleness + PID-reuse contract, and the internal diagnostics marked non-interface.

## Outcome

Consumers have a single documented contract; the flat shape is retained so the existing CLI status reader is untouched.

## Notes

No incidents; no scaffolds left in code.
