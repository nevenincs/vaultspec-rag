---
generated: true
tags:
  - '#index'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
related:
  - '[[2026-06-21-service-first-search-fallback-S01]]'
  - '[[2026-06-21-service-first-search-fallback-S02]]'
  - '[[2026-06-21-service-first-search-fallback-S03]]'
  - '[[2026-06-21-service-first-search-fallback-S04]]'
  - '[[2026-06-21-service-first-search-fallback-S05]]'
  - '[[2026-06-21-service-first-search-fallback-adr]]'
  - '[[2026-06-21-service-first-search-fallback-audit]]'
  - '[[2026-06-21-service-first-search-fallback-plan]]'
  - '[[2026-06-21-service-first-search-fallback-research]]'
---

# `service-first-search-fallback` feature index

Auto-generated index of all documents tagged with `#service-first-search-fallback`.

## Documents

### adr

- `2026-06-21-service-first-search-fallback-adr` - `service-first-search-fallback` adr: `service-first search routing; local always explicit, bounded, torn-down` | (**status:** `accepted`)

### audit

- `2026-06-21-service-first-search-fallback-audit` - `service-first-search-fallback` audit: `code review: service-first search routing and bounded local fallback`

### exec

- `2026-06-21-service-first-search-fallback-S01` - Add a local-mandate resolver (explicit --allow-fallback or configured local-only mode)
- `2026-06-21-service-first-search-fallback-S02` - Make routing service-first by dropping the silent auto-fallback and bare-search local path so a search without a mandate exits service-down
- `2026-06-21-service-first-search-fallback-S03` - Bound any mandated local run with a wall-clock deadline that releases the store lock and exits non-zero on expiry
- `2026-06-21-service-first-search-fallback-S04` - Add regression tests simulating a dead and a wedged service that assert bounded return and a released lock
- `2026-06-21-service-first-search-fallback-S05` - Run lint, type check, and the search and transport test suite

### plan

- `2026-06-21-service-first-search-fallback-plan` - `service-first-search-fallback` plan

### research

- `2026-06-21-service-first-search-fallback-research` - `service-first-search-fallback` research: `degraded-service search hang and silent local fallback (#202)`
