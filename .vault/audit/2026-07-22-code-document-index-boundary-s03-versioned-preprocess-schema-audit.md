---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:1a1521f81a7b0702cf419edcdb3321301c1897b7b5c9f7bfc96a3f792a12882f'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `code-document-index-boundary` audit: `S03 versioned preprocess schema`

## Scope

Audit `W01.P01.S03` against the accepted preprocessing migration boundary. Review schema
versioning, required ownership and extractor identity, worker pickling, and the separation
between schema representation and S04's fail-closed entry-point behavior.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain within S03 scope.

Schema version 2 requires every transform rule to carry a closed `ContentKind` target and a
non-empty caller-managed extractor version. `PreprocessConfig` preserves the declared version
through pickling, while a missing top-level version remains identifiable as legacy version 1.
The rule remains a frozen, primitive-only worker payload.

Focused Ruff, Ty, import, and real TOML-loading checks pass. Non-strict rejection still drops
invalid rules in this Step; S04 owns converting migration and routing defects into a
mutation-free operation refusal.

## Recommendations

Proceed to `W01.P01.S04`. Refuse legacy, unknown-target, and conflicting policies before any
store, cache, metadata, ledger, writer, or GPU resource is opened.
