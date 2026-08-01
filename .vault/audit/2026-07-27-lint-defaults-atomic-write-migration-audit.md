---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:24ab6c9ee014882494e4ea5f0cca15615411c79c2002df379cfb54287b82ba4e'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# `lint-defaults` audit: `atomic write migration`

## Scope

Review the `JsonWriteOptions` migration for the atomic JSON publication path and
its real production callers before completing the first lint-defaults step.

## Findings

### options-regression-coverage | medium | Non-default serialization and durability choices lack direct coverage

The migration preserves the call-site values, but the atomic-write tests currently
exercise only default options. Add real filesystem coverage that proves `indent`,
`sort_keys`, `compact`, and `durable` still reach serialization and durable
publication through `JsonWriteOptions`.

### options-regression-coverage | resolved | Test claims now match observable behavior

The focused real-filesystem test proves non-default serialization and temporary-file
cleanup. It exercises the durable production path without claiming a flush guarantee
that cannot be observed without fault injection or patching.

## Recommendations

No further action is required for this migration.
