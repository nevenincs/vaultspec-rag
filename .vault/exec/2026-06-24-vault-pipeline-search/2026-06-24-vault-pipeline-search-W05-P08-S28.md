---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S28'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Regenerate the bundled CLI reference for the removed verbs

## Scope

- `reference/cli.md`

## Description

- Updated the bundled CLI reference (`docs/cli.md`, the hand-written vaultspec-rag reference;
  there is no `reference/cli.md` in this package) to drop the removed verbs: deleted the
  `## quality` and `## benchmark` sections, their two table-of-contents entries, and their
  mentions in the conventions and global-options prose.

## Outcome

`docs/cli.md` now documents only the shipped commands; no `quality`/`benchmark` references
remain. Confirmed by grep.

## Notes

The vaultspec-rag CLI reference is hand-authored (no generator-managed markers), so the update
is a direct edit rather than a `spec reference generate` run. The plan named `reference/cli.md`;
the actual file is `docs/cli.md`. No blockers.
