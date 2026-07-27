---
generated: true
tags:
  - '#index'
  - '#index-completeness-guard'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - '[[2026-07-25-index-completeness-guard-P01-S01]]'
  - '[[2026-07-25-index-completeness-guard-P01-S02]]'
  - '[[2026-07-25-index-completeness-guard-P01-S03]]'
  - '[[2026-07-25-index-completeness-guard-P02-S04]]'
  - '[[2026-07-25-index-completeness-guard-P02-S05]]'
  - '[[2026-07-25-index-completeness-guard-P02-S06]]'
  - '[[2026-07-25-index-completeness-guard-P03-S07]]'
  - '[[2026-07-25-index-completeness-guard-adr]]'
  - '[[2026-07-25-index-completeness-guard-audit]]'
  - '[[2026-07-25-index-completeness-guard-plan]]'
  - '[[2026-07-25-index-completeness-guard-research]]'
---

# `index-completeness-guard` feature index

Auto-generated index of all documents tagged with `#index-completeness-guard`.

## Documents

### adr

- `2026-07-25-index-completeness-guard-adr` - `index-completeness-guard` adr: `reconcile published evidence against stored breadth and refuse silent partial answers` | (**status:** `accepted`)

### audit

- `2026-07-25-index-completeness-guard-audit` - `index-completeness-guard` audit: `the latch is closed and the silence is broken; the truncation window remains`

### exec

- `2026-07-25-index-completeness-guard-P01-S01` - Persist the point count a code-index publication actually wrote as a reserved metadata key alongside the existing bookkeeping keys
- `2026-07-25-index-completeness-guard-P01-S02` - Replace the existence-only published-evidence check with a shortfall comparison against the published point count, retaining the absent-collection case and escalating only to failure-safe reconciliation
- `2026-07-25-index-completeness-guard-P01-S03` - Prove the shortfall guard can fail by permitting a truncated collection to pass, observing the intended failure, restoring, and observing the pass
- `2026-07-25-index-completeness-guard-P02-S04` - Compute the published-versus-live completeness fact once on the code search path and carry it on the result envelope beside the indexed count
- `2026-07-25-index-completeness-guard-P02-S05` - Render the shortfall as a CLI warning naming the deficit and the remedy on both the service and local search paths, and confirm the MCP code search tool already carries the field without recomputing it
- `2026-07-25-index-completeness-guard-P02-S06` - Prove the completeness warning can fail by suppressing the signal over a truncated index, observing the intended failure, restoring, and observing the pass
- `2026-07-25-index-completeness-guard-P03-S07` - Run the lint, type, citation, complexity, and full test gates and record actual output rather than asserting success

### plan

- `2026-07-25-index-completeness-guard-plan` - `index-completeness-guard` plan

### research

- `2026-07-25-index-completeness-guard-research` - `index-completeness-guard` research: a partially destroyed code collection publishes itself as complete
