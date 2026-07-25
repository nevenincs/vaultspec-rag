---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S10'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Bound the per-path retry and defer on exhaustion, emitting a warning that names the path and the exhausted budget

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Bound supersedes per path and defer the path once its budget is spent.
- Delete the identities the abandoned mutation wrote, so the path keeps
  exactly the content its surviving evidence claims.
- Drop later segments of a deferred path rather than recording them.
- Warn on deferral, naming the path, the number of rewrites observed, and the
  exhausted budget.

## Outcome

A path being rewritten faster than it can be encoded no longer costs the run.
After three supersedes it is deferred: its pending points are removed, its
segments are dropped from this and every later mutation of the run, and the
run completes with the rest of the tree indexed.

Deferral is honest about what it leaves behind. The path keeps its old
published content and its old indexed digest, so the next run sees an ordinary
changed file and re-ingests it. What it must not leave behind is two
generations of content at once, which is why the abandoned identities are
deleted rather than merely unclaimed.

The bound applies to both routes into the remedy, which was not the first
implementation. The budget originally guarded only the refused write, so a
path caught by the cheap pre-record check could be superseded without limit -
the bound existed but the common route walked around it. The test written for
the exhaustion case is what surfaced that, by passing through the cheap route
and never reaching deferral at all.

Deferral is never silent. The warning names the path, how many times it moved,
and the budget it exhausted, because a path that stays stale is an operational
condition an operator has to be able to see.

Gates: lint clean, format clean, type check reports no diagnostics, and the
drift suite passes at 6 tests.

## Notes

The budget is a module constant rather than a configuration knob. Three
rewrites of one file inside one indexing run already describes a tree under
bulk rewrite, and no evidence supports a different number; adding an operator
knob would invite tuning a value nobody can observe the effect of.
