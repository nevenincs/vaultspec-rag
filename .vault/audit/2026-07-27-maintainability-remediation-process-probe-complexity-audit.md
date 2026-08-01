---
tags:
  - '#audit'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:3b2f4a23315ba904c771d0a532afd426db74d4006f6c0f5a18ab44291a2f96dc'
related: []
---

# `maintainability-remediation` audit: `process probe complexity`

## Scope

Reviewed the cognitive-complexity decomposition of the process-probe ownership,
vocabulary, source-structure, and service-contract guard tests. The review
preserved their production-tree assertions while separating AST traversal from
the domain-specific predicate each guard enforces.

## Findings

### shared-worktree-corruption | critical | Concurrent edits invalidated final verification

Immediately after a successful health run and focused guard-test run, concurrent
shared-worktree edits introduced form-feed-corrupted imports into two reviewed
test modules. Format, lint, test collection, and a subsequent health run can no
longer parse the affected files. The corruption is outside this review's edit
scope and must be repaired by its owner before final verification is repeated.

### complexity-score-report | low | Reviewer observation superseded by direct health evidence

The independent reviewer reported the original high scores while reading the
later-corrupted files. Before that concurrent change, `just health` completed
successfully and no longer listed the requested guards; the focused refactored
guards also passed. Treat the reviewer observation as stale rather than a
remaining remediation task.

## Recommendations

Restore the malformed imports in the owning concurrent change, then rerun the
focused guard tests, format and lint checks, and `just health`. Do not weaken
the duplicate-structure guards to accommodate the independent production
duplicates currently reported by their unchanged assertions.
