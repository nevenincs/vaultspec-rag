---
generated: true
tags:
  - '#index'
  - '#control-plane-affordances'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - '[[2026-07-13-control-plane-affordances-P01-S01]]'
  - '[[2026-07-13-control-plane-affordances-P01-S02]]'
  - '[[2026-07-13-control-plane-affordances-P01-S03]]'
  - '[[2026-07-13-control-plane-affordances-P01-S04]]'
  - '[[2026-07-13-control-plane-affordances-P01-summary]]'
  - '[[2026-07-13-control-plane-affordances-P02-S05]]'
  - '[[2026-07-13-control-plane-affordances-P02-S06]]'
  - '[[2026-07-13-control-plane-affordances-P02-summary]]'
  - '[[2026-07-13-control-plane-affordances-adr]]'
  - '[[2026-07-13-control-plane-affordances-audit]]'
  - '[[2026-07-13-control-plane-affordances-plan]]'
  - '[[2026-07-13-control-plane-affordances-research]]'
---

# `control-plane-affordances` feature index

Auto-generated index of all documents tagged with `#control-plane-affordances`.

## Documents

### adr

- `2026-07-13-control-plane-affordances-adr` - `control-plane-affordances` adr: `root-scoped survey lookup and stop --json parity` | (**status:** `accepted`)

### audit

- `2026-07-13-control-plane-affordances-audit` - `control-plane-affordances` audit: `execution review of the survey root lookup and stop --json`

### exec

- `2026-07-13-control-plane-affordances-P01-S01` - Extend the storage survey route to accept an optional root query parameter, resolve it through root_collection_prefix, narrow the namespace list to the matching prefix, and add the top-level queried_root object (present only when root is passed, returned even for unindexed roots)
- `2026-07-13-control-plane-affordances-P01-S02` - Admit root into the survey transport params and thread the optional root argument through the MCP survey client and the get_storage_survey tool surface
- `2026-07-13-control-plane-affordances-P01-S03` - Add --root to server storage survey, pass it through both the service-first and CLI-direct paths, and render queried_root in human and --json output
- `2026-07-13-control-plane-affordances-P01-S04` - Cover the root-scoped lookup end to end: indexed root returns prefix plus populated namespaces, unindexed root returns prefix plus empty list, and the CLI and MCP adapters pass the parameter through
- `2026-07-13-control-plane-affordances-P01-summary` - `control-plane-affordances` `P01` summary
- `2026-07-13-control-plane-affordances-P02-S05` - Add --json to server stop with one envelope per exit path (stopped, already_stopped, cleaned, reclaimed as ok:true and identity_unconfirmed as ok:false) and make the identity-unconfirmed skip exit 1 in both human and json modes, covering the --port variant
- `2026-07-13-control-plane-affordances-P02-S06` - Assert the stop --json envelope and exit code on each exit path alongside the existing start --json matrix
- `2026-07-13-control-plane-affordances-P02-summary` - `control-plane-affordances` `P02` summary

### plan

- `2026-07-13-control-plane-affordances-plan` - `control-plane-affordances` plan

### research

- `2026-07-13-control-plane-affordances-research` - `control-plane-affordances` research: `root-scoped survey lookup and stop --json parity`
