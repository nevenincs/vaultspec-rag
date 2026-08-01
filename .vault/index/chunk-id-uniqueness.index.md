---
generated: true
tags:
  - '#index'
  - '#chunk-id-uniqueness'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:00addc5dfc0a01e7cccf825d4bfc226c44736c92cda62c906f6adbcc84bf606f'
related:
  - '[[2026-07-23-chunk-id-uniqueness-S01]]'
  - '[[2026-07-23-chunk-id-uniqueness-S02]]'
  - '[[2026-07-23-chunk-id-uniqueness-S03]]'
  - '[[2026-07-23-chunk-id-uniqueness-S04]]'
  - '[[2026-07-23-chunk-id-uniqueness-adr]]'
  - '[[2026-07-23-chunk-id-uniqueness-plan]]'
  - '[[2026-07-23-chunk-id-uniqueness-research]]'
---

# `chunk-id-uniqueness` feature index

Auto-generated index of all documents tagged with `#chunk-id-uniqueness`.

## Documents

### adr

- `2026-07-23-chunk-id-uniqueness-adr` - `chunk-id-uniqueness` adr: `ordinal-disambiguated chunk identifiers` | (**status:** `accepted`)

### exec

- `2026-07-23-chunk-id-uniqueness-S01` - Add the zero-based per-file emit ordinal as a leading discriminator to the AST-path chunk identifier so byte-identical slices of one line cannot collide
- `2026-07-23-chunk-id-uniqueness-S02` - Add the same per-file emit ordinal discriminator to the text-splitter fallback chunk identifier
- `2026-07-23-chunk-id-uniqueness-S03` - Add a guard test that chunks a repeated-content over-budget line through the real chunker, asserts unique identifiers and commit-unit acceptance, and record it failing against the pre-fix construction then passing after
- `2026-07-23-chunk-id-uniqueness-S04` - Run the indexer test suite plus lint and type checks for the touched modules and record them green with no new suppressions

### plan

- `2026-07-23-chunk-id-uniqueness-plan` - `chunk-id-uniqueness` plan

### research

- `2026-07-23-chunk-id-uniqueness-research` - `chunk-id-uniqueness` research: `code chunk id collisions on repeated-content long lines`
