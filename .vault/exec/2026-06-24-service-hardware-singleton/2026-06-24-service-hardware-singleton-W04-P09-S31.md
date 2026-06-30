---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-30'
step_id: 'S31'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Codify that any test or caller of write_qdrant_identity or acquire_machine_lock must isolate VAULTSPEC_RAG_QDRANT_STORAGE_DIR or it writes the real machine-global path, after a leaked identity sidecar was observed

## Scope

- `.vaultspec/rules/rules/`

## Description

- Codify that any test or caller exercising `write_qdrant_identity` or
  `acquire_machine_lock` must isolate `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a
  temp path, after the audit observed a leaked identity sidecar written to the
  real machine-global managed dir.
- Scaffold the rule with `vaultspec-core spec rules add` under the canonical
  slug, then author the Rule/Why/How body per the codify discipline.
- Name the originating audit in the Why section, explain that the machine lock
  shares the storage parent so an unisolated test contends for the real machine
  singleton, and record that the constraint held across one full execution cycle.
- Run `vaultspec-core sync` to propagate the rule to every provider surface.

## Outcome

The rule ships under the project rules directory and is listed by
`vaultspec-core spec rules list`; `vaultspec-core sync` created its provider
mirrors and added it to the assembled system prompt. A future agent now inherits
the storage-dir isolation requirement on load.

## Notes

The candidate qualified for promotion only after this lifecycle pass confirmed it
across the cycle (the leak, the `_service_env` storage-dir fix, and the S29
binary-mirror follow-up that keeps the storage dir relocated), per the codify
rule's "never codify on the first encounter" bar.
